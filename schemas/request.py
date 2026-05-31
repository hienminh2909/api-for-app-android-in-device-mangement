from pydantic import BaseModel
from typing import Optional, Any

class RequestCreate(BaseModel):
    device_code: str # Đổi từ device_id (int) sang device_code (str) để khớp với mã QR
    description: str
    status_device: Optional[str] = "pending"
    request_type: Optional[str] = "REPORT" # REPORT, UPDATE, DELETE
    update_payload: Optional[Any] = None
