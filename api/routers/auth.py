from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
from jose import jwt

from core.config import supabase, SECRET_KEY, ALGORITHM
from services.auth_service import get_current_user
from schemas.auth import LoginRequest, ChangePasswordRequest, ForgotPasswordRequest

router = APIRouter()

@router.post("/login")
async def login(req: LoginRequest):
    res = supabase.table("users").select("*").eq("username", req.username).execute()
    user = res.data[0] if res.data else None

    if not user or user['password_hash'] != req.password:
        raise HTTPException(status_code=401, detail="Tài khoản hoặc mật khẩu không đúng")

    token_data = {
        "user_id": user['id'],
        "role": user['role'],
        "full_name": user['full_name'],
        "username": user['username'],
        "room_id": user.get('room_id'), 
        "exp": (datetime.utcnow() + timedelta(hours=7)) + timedelta(days=1)
    }
    
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user['role'],
        "full_name": user['full_name']
    }

@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    # 1. Tìm user
    res = supabase.table("users").select("id, full_name").eq("username", req.username).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Tên đăng nhập không tồn tại")
    
    user = res.data[0]

    # 2. Tìm ID của Admin
    admin_res = supabase.table("users").select("id").eq("role", "admin").limit(1).execute()
    if not admin_res.data:
        raise HTTPException(status_code=500, detail="Không tìm thấy Quản trị viên trong hệ thống")
    admin_id = admin_res.data[0]['id']

    # 3. Tạo thông báo cho Admin
    try:
        from api.routers.notifications import create_notification
        notif_content = f"Người dùng {user['full_name']} (@{req.username}) đã gửi yêu cầu đặt lại mật khẩu."
        create_notification(
            user_id=admin_id,
            title="Yêu cầu khôi phục mật khẩu",
            content=notif_content,
            link=None
        )
        
        return {"message": "Vui lòng đợi Admin liên hệ lại để cấp lại mật khẩu."}
    except Exception as e:
        # Xử lý lỗi tạo thông báo
        print(f"Lỗi khi tạo thông báo forgot-password: {e}")
        return {"message": "Vui lòng đợi Admin liên hệ lại để cấp lại mật khẩu."}

@router.put("/password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    user_id = user.get("user_id")
    try:
        res = supabase.table("users").select("password_hash").eq("id", user_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
            
        current_password_hash = res.data[0]['password_hash']
        
        if current_password_hash != req.old_password:
            raise HTTPException(status_code=400, detail="Mật khẩu cũ không chính xác")

        update_res = supabase.table("users").update({"password_hash": req.new_password}).eq("id", user_id).execute()
        
        if update_res.data:
            return {"message": "Đổi mật khẩu thành công"}
        else:
            raise HTTPException(status_code=500, detail="Cập nhật mật khẩu thất bại")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")
