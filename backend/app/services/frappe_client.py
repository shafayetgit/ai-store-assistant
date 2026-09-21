import logging
from typing import Any
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class FrappeAPIError(Exception):
    """Raised when the Frappe / ERPNext API returns an error."""
    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class FrappeClient:
    """
    Async client for Frappe / ERPNext Webshop REST API (hnbpark.com).
    Uses token authentication: 'token {api_key}:{api_secret}'.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or settings.STORE_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.STORE_API_KEY
        self.api_secret = api_secret or settings.STORE_API_SECRET
        self.timeout = timeout or settings.STORE_TIMEOUT_SECONDS

    @property
    def is_configured(self) -> bool:
        """Returns True if store API credentials are provided."""
        return bool(self.api_key and self.api_secret)

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.is_configured:
            headers["Authorization"] = f"token {self.api_key}:{self.api_secret}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Executes an HTTP request to the Frappe REST API with error handling."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 401 or response.status_code == 403:
                    raise FrappeAPIError(
                        f"Authentication failed on {self.base_url} (HTTP {response.status_code}). Check STORE_API_KEY and STORE_API_SECRET.",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                if response.status_code == 404:
                    return {}

                response.raise_for_status()
                return response.json()

            except httpx.ConnectError as exc:
                logger.error(f"Cannot connect to store backend at {self.base_url}: {exc}")
                raise FrappeAPIError(f"Connection to store backend failed: {exc}") from exc
            except httpx.TimeoutException as exc:
                logger.error(f"Timeout contacting store backend at {self.base_url}: {exc}")
                raise FrappeAPIError(f"Store backend timed out after {self.timeout}s") from exc
            except httpx.HTTPStatusError as exc:
                logger.error(f"HTTP error {exc.response.status_code} from store backend: {exc.response.text}")
                raise FrappeAPIError(
                    f"Store backend error: {exc.response.text}",
                    status_code=exc.response.status_code,
                    response_body=exc.response.text,
                ) from exc

    # ━━ Connection & Health ━━
    async def get_logged_user(self) -> dict[str, Any]:
        """Verifies API key credentials against Frappe."""
        if not self.is_configured:
            return {"status": "unconfigured", "message": "STORE_API_KEY or STORE_API_SECRET is empty."}
        try:
            data = await self._request("GET", "/api/method/frappe.auth.get_logged_user")
            return {"status": "connected", "user": data.get("message")}
        except FrappeAPIError as err:
            return {"status": "error", "message": str(err)}

    # ━━ Catalog & Items ━━
    async def get_item(self, item_code: str) -> dict[str, Any] | None:
        """Fetch item details by Item Code / SKU."""
        data = await self._request("GET", f"/api/resource/Item/{item_code}")
        return data.get("data") if data else None

    async def search_items(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search items in Frappe by keyword in item_name or item_code."""
        import json
        filters = [["disabled", "=", 0], ["item_name", "like", f"%{query}%"]]
        fields = ["name", "item_code", "item_name", "item_group", "description", "stock_uom", "image"]

        params = {
            "filters": json.dumps(filters),
            "fields": json.dumps(fields),
            "limit_page_length": limit,
        }
        data = await self._request("GET", "/api/resource/Item", params=params)
        return data.get("data", [])

    async def list_website_items(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch published Website Items with pricing and images."""
        import json
        fields = ["name", "item_code", "item_name", "item_group", "web_item_name", "route", "website_image"]
        params = {
            "fields": json.dumps(fields),
            "limit_page_length": limit,
        }
        data = await self._request("GET", "/api/resource/Website Item", params=params)
        return data.get("data", [])

    # ━━ Sales Orders & Tracking ━━
    async def get_sales_order(self, order_name: str) -> dict[str, Any] | None:
        """Fetch a specific Sales Order with line items, delivery status, and tracking."""
        data = await self._request("GET", f"/api/resource/Sales Order/{order_name}")
        return data.get("data") if data else None

    async def get_customer_orders(self, customer_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Fetch recent Sales Orders for a customer."""
        import json
        filters = [["customer", "=", customer_name], ["docstatus", "<", 2]]
        fields = ["name", "customer", "transaction_date", "grand_total", "currency", "status", "delivery_status"]
        params = {
            "filters": json.dumps(filters),
            "fields": json.dumps(fields),
            "order_by": "creation desc",
            "limit_page_length": limit,
        }
        data = await self._request("GET", "/api/resource/Sales Order", params=params)
        return data.get("data", [])

    # ━━ Customer Support & Leads ━━
    async def create_issue(
        self,
        subject: str,
        description: str,
        raised_by: str,
        priority: str = "Medium",
    ) -> dict[str, Any]:
        """Create a customer support ticket in Frappe / ERPNext."""
        payload = {
            "subject": subject,
            "description": description,
            "raised_by": raised_by,
            "priority": priority,
            "status": "Open",
        }
        data = await self._request("POST", "/api/resource/Issue", json_data=payload)
        return data.get("data", {})

    async def create_lead(
        self,
        lead_name: str,
        email: str | None = None,
        phone: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create a sales lead in Frappe / ERPNext."""
        payload: dict[str, Any] = {"lead_name": lead_name}
        if email:
            payload["email_id"] = email
        if phone:
            payload["mobile_no"] = phone
        if notes:
            payload["notes"] = [{"note": notes}]

        data = await self._request("POST", "/api/resource/Lead", json_data=payload)
        return data.get("data", {})


# Global singleton instance
frappe_client = FrappeClient()