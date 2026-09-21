import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.customer import Customer
from app.models.conversation import Conversation, ConversationState
from app.models.message import Message, SenderType
from app.services.llm_client import llm_client
from app.services.prompt_templates import build_system_prompt
from app.services.store_tools import STORE_TOOLS, execute_tool

logger = logging.getLogger(__name__)


class AgentService:
    """
    Multi-turn agent orchestrator. Manages state, message persistence,
    and tool execution loops for omnichannel store assistance.
    """

    async def _load_history(
        self,
        db: AsyncSession,
        conversation: Conversation,
        history_limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Loads and formats recent messages for OpenAI chat completion."""
        # Safely load customer without triggering synchronous lazy-loading
        customer = None
        if conversation.customer_id:
            cust_stmt = select(Customer).where(Customer.id == conversation.customer_id)
            customer = (await db.execute(cust_stmt)).scalar_one_or_none()

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    customer=customer,
                    channel=conversation.channel_type,
                    extra_context=conversation.metadata_info,
                ),
            }
        ]

        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(history_limit)
        )
        res = await db.execute(stmt)
        past_turns = list(reversed(res.scalars().all()))

        for m in past_turns:
            if m.sender_type == SenderType.USER.value:
                messages.append({"role": "user", "content": m.content or ""})
            elif m.sender_type == SenderType.ASSISTANT.value:
                entry: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
                if m.tool_calls:
                    entry["tool_calls"] = m.tool_calls
                messages.append(entry)
            elif m.sender_type == SenderType.TOOL.value and m.raw_payload:
                messages.append({
                    "role": "tool",
                    "tool_call_id": m.raw_payload.get("tool_call_id", str(uuid.uuid4())),
                    "name": m.raw_payload.get("tool_name", "tool"),
                    "content": m.content or "",
                })

        return messages

    async def process_message(
        self,
        db: AsyncSession,
        conversation: Conversation,
        user_text: str,
        max_turns: int | None = None,
    ) -> str:
        """
        Processes an incoming customer message synchronously (for Messenger webhook / Celery).
        Returns the final assistant response string.
        """
        # 1. Yield to human support if conversation was handed off
        if conversation.session_state in (ConversationState.HUMAN_REQUESTED.value, ConversationState.HUMAN_ACTIVE.value):
            logger.info(f"Conversation {conversation.id} is with human staff. Saving message without AI response.")
            user_msg = Message(
                conversation_id=conversation.id,
                sender_type=SenderType.USER.value,
                content=user_text,
            )
            db.add(user_msg)
            await db.commit()
            return settings.OFF_HOURS_MESSAGE if conversation.session_state == ConversationState.HUMAN_REQUESTED.value else ""

        # 2. Persist incoming user message
        user_msg = Message(
            conversation_id=conversation.id,
            sender_type=SenderType.USER.value,
            content=user_text,
        )
        db.add(user_msg)
        await db.flush()

        # 3. Assemble chat history
        messages = await self._load_history(db, conversation)
        turns_left = max_turns or settings.LLM_MAX_TOOL_TURNS
        final_reply = ""

        # 4. Multi-Turn Autonomous Tool Loop
        while turns_left > 0:
            turns_left -= 1
            response = await llm_client.chat_completion(messages=messages, tools=STORE_TOOLS)

            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")

            # A. Model requested tool executions
            if tool_calls:
                logger.info(f"Agent requested {len(tool_calls)} tool call(s): {[t['function']['name'] for t in tool_calls]}")

                # Save assistant's tool-call decision to DB
                asst_tool_msg = Message(
                    conversation_id=conversation.id,
                    sender_type=SenderType.ASSISTANT.value,
                    content=content,
                    tool_calls=tool_calls,
                )
                db.add(asst_tool_msg)
                messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

                # Execute each tool
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]

                    result = await execute_tool(
                        tool_name=fn_name,
                        arguments=fn_args,
                        db=db,
                        conversation_id=conversation.id,
                        customer_id=conversation.customer_id,
                    )

                    result_str = json.dumps(result, ensure_ascii=False)

                    # Persist tool execution output
                    tool_msg = Message(
                        conversation_id=conversation.id,
                        sender_type=SenderType.TOOL.value,
                        content=result_str,
                        raw_payload={"tool_call_id": tc["id"], "tool_name": fn_name},
                    )
                    db.add(tool_msg)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": result_str,
                    })

                await db.flush()
                # Continue loop so LLM can synthesize tool results
                continue

            # B. Final text response produced
            final_reply = content
            bot_msg = Message(
                conversation_id=conversation.id,
                sender_type=SenderType.ASSISTANT.value,
                content=final_reply,
            )
            db.add(bot_msg)
            conversation.last_active_at = datetime.now(timezone.utc)
            await db.commit()
            break

        if not final_reply and messages[-1]["role"] == "tool":
            final_res = await llm_client.chat_completion(messages=messages, tools=None)
            final_reply = final_res.get("content", "")
            if final_reply:
                bot_msg = Message(
                    conversation_id=conversation.id,
                    sender_type=SenderType.ASSISTANT.value,
                    content=final_reply,
                )
                db.add(bot_msg)
                conversation.last_active_at = datetime.now(timezone.utc)
                await db.commit()

        return final_reply

    async def stream_message(
        self,
        db: AsyncSession,
        conversation: Conversation,
        user_text: str,
    ) -> AsyncGenerator[str, None]:
        """
        Streams assistant response tokens for Website Chat SSE streaming.
        Runs tool loop first if required, then streams final text.
        """
        if conversation.session_state in (ConversationState.HUMAN_REQUESTED.value, ConversationState.HUMAN_ACTIVE.value):
            user_msg = Message(
                conversation_id=conversation.id,
                sender_type=SenderType.USER.value,
                content=user_text,
            )
            db.add(user_msg)
            await db.commit()
            yield "Your conversation is with a human representative."
            return

        user_msg = Message(
            conversation_id=conversation.id,
            sender_type=SenderType.USER.value,
            content=user_text,
        )
        db.add(user_msg)
        await db.flush()

        messages = await self._load_history(db, conversation)
        turns_left = settings.LLM_MAX_TOOL_TURNS

        # Tool execution loop
        while turns_left > 0:
            turns_left -= 1
            response = await llm_client.chat_completion(messages=messages, tools=STORE_TOOLS)
            tool_calls = response.get("tool_calls", [])

            if tool_calls:
                asst_tool_msg = Message(
                    conversation_id=conversation.id,
                    sender_type=SenderType.ASSISTANT.value,
                    content=response.get("content", ""),
                    tool_calls=tool_calls,
                )
                db.add(asst_tool_msg)
                messages.append({"role": "assistant", "content": response.get("content", ""), "tool_calls": tool_calls})

                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                    result = await execute_tool(
                        tool_name=fn_name,
                        arguments=fn_args,
                        db=db,
                        conversation_id=conversation.id,
                        customer_id=conversation.customer_id,
                    )
                    res_str = json.dumps(result, ensure_ascii=False)
                    db.add(Message(
                        conversation_id=conversation.id,
                        sender_type=SenderType.TOOL.value,
                        content=res_str,
                        raw_payload={"tool_call_id": tc["id"], "tool_name": fn_name},
                    ))
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "name": fn_name, "content": res_str})

                await db.flush()
                continue
            else:
                # No tool calls needed; stream final response
                break

        # Stream the final answer tokens
        accumulated_reply: list[str] = []
        async for token in llm_client.stream_chat_completion(messages=messages):
            accumulated_reply.append(token)
            yield token

        final_text = "".join(accumulated_reply)
        db.add(Message(
            conversation_id=conversation.id,
            sender_type=SenderType.ASSISTANT.value,
            content=final_text,
        ))
        conversation.last_active_at = datetime.now(timezone.utc)
        await db.commit()


agent_service = AgentService()