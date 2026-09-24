import logging, json
from typing import Any
from urllib.parse import quote
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
        encoded_sku = quote(item_code.strip(), safe="")
        data = await self._request("GET", f"/api/resource/Item/{encoded_sku}")
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

    async def get_full_website_item(self, web_item_name: str) -> dict[str, Any] | None:
        """
        Fetches the complete Website Item document including child tables
        like website_specifications, tabs, and rich descriptions.
        """
        encoded_name = quote(web_item_name.strip(), safe="")
        data = await self._request("GET", f"/api/resource/Website Item/{encoded_name}")
        return data.get("data") if data else None

    async def get_item_variants(self, template_item_code: str) -> list[dict[str, Any]]:
        """
        Fetches all child variant items for a given template item code
        (where variant_of == template_item_code), whether published or not.
        Also retrieves each variant's attributes (e.g., Color, Size, Model).
        """
        try:
            res = await self._request(
                method="GET",
                path="api/resource/Item",
                params={
                    "filters": json.dumps({"variant_of": template_item_code, "disabled": 0}),
                    "fields": json.dumps([
                        "name",
                        "item_code",
                        "item_name",
                        "item_group",
                        "image",
                        "description",
                        "stock_uom",
                        "variant_of",
                    ]),
                    "limit_page_length": 100,
                },
            )
            raw_variants = res.get("data", [])
            variants: list[dict[str, Any]] = []

            for var in raw_variants:
                code = var.get("item_code") or var.get("name")
                if not code:
                    continue
                # Fetch full item doc to get variant attributes child table
                try:
                    full_doc = await self.get_item(code)
                    var["attributes_list"] = full_doc.get("attributes", [])
                    var["image"] = var.get("image") or full_doc.get("image")
                except Exception as doc_err:
                    logger.warning(f"Could not fetch full doc for variant {code}: {doc_err}")
                    var["attributes_list"] = []

                variants.append(var)

            return variants
        except Exception as exc:
            logger.warning(f"Failed to fetch variants for template {template_item_code}: {exc}")
            return []


    async def get_item_price_and_stock(self, item_code: str) -> dict[str, Any]:
        """
        Fetches the active selling price from 'Item Price' and on-hand inventory
        from 'Bin' for a specific SKU.
        """
        import json
        clean_code = item_code.strip()
        price_val = 0.0
        currency = "BDT"
        actual_qty = 0

        # 1. Fetch Item Price
        try:
            price_res = await self._request(
                "GET",
                "/api/resource/Item Price",
                params={
                    "filters": json.dumps([["item_code", "=", clean_code]]),
                    "fields": json.dumps(["name", "price_list_rate", "currency"]),
                    "limit_page_length": 1,
                },
            )
            price_records = price_res.get("data", [])
            if price_records:
                price_val = float(price_records[0].get("price_list_rate") or 0.0)
                currency = price_records[0].get("currency") or "BDT"
        except Exception as exc:
            logger.warning(f"Failed to fetch Item Price for {clean_code}: {exc}")

        # 2. Fetch Stock Bin
        try:
            bin_res = await self._request(
                "GET",
                "/api/resource/Bin",
                params={
                    "filters": json.dumps([["item_code", "=", clean_code]]),
                    "fields": json.dumps(["actual_qty", "warehouse"]),
                },
            )
            bin_records = bin_res.get("data", [])
            if bin_records:
                actual_qty = int(sum(float(b.get("actual_qty") or 0) for b in bin_records))
        except Exception as exc:
            logger.warning(f"Failed to fetch Stock Bins for {clean_code}: {exc}")

        return {
            "price": price_val,
            "currency": currency,
            "stock_quantity": actual_qty,
        }


    # ━━ Sales Orders & Tracking ━━
    async def get_sales_order(self, order_name: str) -> dict[str, Any] | None:
        """Fetch a specific Sales Order with line items, delivery status, and tracking."""
        encoded_order = quote(order_name.strip(), safe="")
        data = await self._request("GET", f"/api/resource/Sales Order/{encoded_order}")
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