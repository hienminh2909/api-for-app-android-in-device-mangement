from fastapi import APIRouter, Depends, HTTPException
from core.config import supabase
from services.auth_service import get_current_user
from pydantic import BaseModel
from typing import Optional
import time
import uuid
from datetime import datetime, timedelta

router = APIRouter()

class UserCreate(BaseModel):
    full_name: str
    username: str
    password_hash: str
    role: str = "teacher"
    room_name: Optional[str] = None # Nhận tên phòng thay vì ID
    phone: Optional[str] = None
    email: Optional[str] = None
    handheld_name: Optional[str] = None

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    username: Optional[str] = None
    password_hash: Optional[str] = None
    role: Optional[str] = None
    room_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    handheld_name: Optional[str] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

@router.get("/me")
async def get_my_profile(user: dict = Depends(get_current_user)):
    res = supabase.table("users").select("id, full_name, username, role, room_id, phone, email, handheld_name, created_at").eq("id", user.get("user_id")).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông tin")
    return res.data[0]

@router.put("/me/update")
async def update_my_profile(req: UserUpdate, user: dict = Depends(get_current_user)):
    try:
        # Lọc các trường được phép
        update_data = {k: v for k, v in req.dict().items() if v is not None and k in ["full_name", "phone", "email"]}
        
        if user.get("role") == "admin":
            # Admin đổi trực tiếp
            res = supabase.table("users").update(update_data).eq("id", user.get("user_id")).execute()
            return {"message": "Đã cập nhật thông tin cá nhân thành công", "status": "approved"}
        else:
            # User (Teacher) gửi yêu cầu cho Admin
            request_data = {
                "created_by": user.get("user_id"),
                "description": f"Yêu cầu đổi thông tin cá nhân: Tên ({update_data.get('full_name', '')}), SĐT ({update_data.get('phone', '')}), Email ({update_data.get('email', '')})",
                "status_device": "pending",
                "status_resolve": "pending",
                "request_type": "UPDATE_USER",
                "update_payload": update_data,
                "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
            }
            res = supabase.table("requests").insert(request_data).execute()
            
            # Gửi thông báo cho Admin
            try:
                from api.routers.notifications import create_notification
                admins = supabase.table("users").select("id").eq("role", "admin").execute()
                for admin in admins.data:
                    create_notification(
                        user_id=admin["id"],
                        title="Yêu cầu duyệt thông tin",
                        content=f"Người dùng {user.get('full_name')} (@{user.get('username')}) yêu cầu đổi thông tin cá nhân.",
                        link="/requests",
                        created_by=user.get("user_id")
                    )
            except Exception as e_notif:
                print(f"Lỗi gửi thông báo: {e_notif}")

            return {"message": "Đã gửi yêu cầu cho Admin duyệt", "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/me/change-password")
async def change_password(req: PasswordChange, user: dict = Depends(get_current_user)):
    # 1. Kiểm tra mật khẩu cũ
    user_res = supabase.table("users").select("password_hash").eq("id", user.get("user_id")).execute()
    if not user_res.data or user_res.data[0]["password_hash"] != req.old_password:
        raise HTTPException(status_code=400, detail="Mật khẩu cũ không chính xác")
    
    # 2. Cập nhật mật khẩu mới
    try:
        supabase.table("users").update({"password_hash": req.new_password}).eq("id", user.get("user_id")).execute()
        return {"message": "Đổi mật khẩu thành công"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("")
async def get_users(user: dict = Depends(get_current_user)):
    res = supabase.table("users").select("id, full_name, username, password_hash, role, room_id, phone, email, handheld_name, created_at, rooms(room_name)").execute()
    
    # Flatten rooms(room_name) and filter deleted users
    valid_users = []
    for u in res.data:
        if "_deleted_" in u.get("username", ""):
            continue
            
        if u.get("rooms"):
            u["room_name"] = u["rooms"].get("room_name")
        else:
            u["room_name"] = "Tất cả"
        valid_users.append(u)
            
    return valid_users

@router.post("")
async def create_user(req: UserCreate, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền thao tác")
    try:
        user_data = req.dict(exclude={"room_name"})
        
        # Xử lý tự động đăng ký phòng mới
        if req.room_name and req.room_name.strip():
            room_name = req.room_name.strip()
            # Kiểm tra xem phòng đã tồn tại chưa
            room_res = supabase.table("rooms").select("id").eq("room_name", room_name).execute()
            
            if room_res.data:
                room_id = room_res.data[0]['id']
            else:
                # Nếu chưa có thì tạo mới
                new_room_res = supabase.table("rooms").insert({"room_name": room_name}).execute()
                if not new_room_res.data:
                    raise HTTPException(status_code=400, detail="Không thể tạo phòng mới")
                room_id = new_room_res.data[0]['id']
            
            user_data["room_id"] = room_id

        res = supabase.table("users").insert(user_data).execute()
        
        print(f"DEBUG: Insert User Data: {user_data}")
        print(f"DEBUG: Supabase Response: {res}")

        if not res.data:
            print("DEBUG: Insertion failed - no data returned")
            raise HTTPException(status_code=400, detail="Không thể tạo người dùng. Username có thể đã tồn tại.")
        
        return res.data[0]
    except Exception as e:
        print(f"DEBUG: Error creating user: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{user_id}")
async def update_user(user_id: int, req: UserUpdate, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền thao tác")
    try:
        update_data = {k: v for k, v in req.dict().items() if v is not None}
        res = supabase.table("users").update(update_data).eq("id", user_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng để cập nhật")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{user_id}/reset-password")
async def reset_user_password(user_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền thao tác")
    try:
        # Đặt lại mật khẩu mặc định là 123456
        res = supabase.table("users").update({"password_hash": "123456"}).eq("id", user_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
        return {"message": "Đã đặt lại mật khẩu về 123456"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền thao tác")
    try:
        # Lấy thông tin user cũ
        old_user_res = supabase.table("users").select("username, full_name").eq("id", user_id).execute()
        if not old_user_res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
            
        old_user = old_user_res.data[0]
        
        # Cập nhật thông tin để xóa mềm (Soft Delete)
        new_username = f"{old_user['username']}_deleted_{int(time.time())}"
        new_full_name = f"[Đã xóa] {old_user['full_name']}"
        random_password = str(uuid.uuid4())
        
        update_data = {
            "username": new_username,
            "full_name": new_full_name,
            "password_hash": random_password,
            "updated_at": (datetime.utcnow() + timedelta(hours=7)).isoformat(),
            "room_id": None
        }
        
        res = supabase.table("users").update(update_data).eq("id", user_id).execute()
        return {"message": "Đã xóa thành công"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
