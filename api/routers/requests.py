<<<<<<< HEAD
from fastapi import APIRouter, Depends, HTTPException
from core.config import supabase
from services.auth_service import get_current_user
from schemas.request import RequestCreate
from datetime import datetime, timedelta
from api.routers.notifications import create_notification

router = APIRouter()

@router.post("")
async def create_request(req: RequestCreate, user: dict = Depends(get_current_user)):
    try:
        # TÌM ID THIẾT BỊ TỪ DEVICE_CODE
        dev_res = supabase.table("devices").select("id, device_name, device_code, rooms(room_name)").eq("device_code", req.device_code).execute()
        if not dev_res.data:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy thiết bị có mã: {req.device_code}")
        
        device_id = dev_res.data[0]["id"]

        # Xác định trạng thái thiết bị mong muốn
        intended_status = req.status_device
        if req.request_type == "REPORT" and (not intended_status or intended_status == "pending"):
            intended_status = "Hỏng"

        request_data = {
            "device_id": device_id,
            "created_by": user.get("user_id"),
            "description": req.description,
            "status_device": intended_status if intended_status else "pending",
            "status_resolve": "pending", # Trỏ pending vào status_resolve theo yêu cầu
            "request_type": req.request_type,
            "update_payload": req.update_payload,
            "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
        }
        
        print(f"DEBUG: Maintenance Request Data: {request_data}")
        res = supabase.table("requests").insert(request_data).execute()
        print(f"DEBUG: Supabase Request Insert Response: {res}")
        
        if res.data:
            # THÔNG BÁO CHO ADMIN (Chỉ gửi nếu người tạo KHÔNG PHẢI là admin)
            if user.get("role") != "admin":
                try:
                    admins = supabase.table("users").select("id").eq("role", "admin").execute()
                    notif_link = "/requests?tab=advanced" if req.request_type != "REPORT" else "/requests"
                    for admin in admins.data:
                        # Không gửi thông báo cho chính mình nếu mình là admin (đã check ở trên nhưng check lại cho chắc)
                        if admin["id"] != user.get("user_id"):
                            device_info = dev_res.data[0]
                            d_name = device_info.get("device_name", "N/A")
                            d_code = device_info.get("device_code", "N/A")
                            r_name = "Phòng không xác định"
                            if device_info.get("rooms"):
                                r_name = device_info["rooms"].get("room_name", "Phòng không xác định")

                            role_str = "Giáo viên" if str(user.get("role")) == "teacher" else "Admin"
                            req_type_vi = ""
                            if req.request_type == "REPORT": req_type_vi = "báo cáo trạng thái"
                            elif req.request_type == "UPDATE": req_type_vi = "sửa thông tin"
                            elif req.request_type == "DELETE": req_type_vi = "xóa"
                            else: req_type_vi = "xử lý"

                            create_notification(
                                user_id=admin["id"],
                                title="Yêu cầu mới cần phê duyệt",
                                content=f"{role_str} {user.get('full_name')} yêu cầu {req_type_vi} thiết bị {d_name} ({d_code}) tại {r_name}",
                                link=notif_link,
                                created_by=user.get("user_id")
                            )
                except Exception as e_notif:
                    print(f"DEBUG: Notification failed but request saved: {str(e_notif)}")
        
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"DEBUG: Error in create_request: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/pending")
async def get_pending_requests(user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).lower()
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền xem yêu cầu")
    
    # Lấy các yêu cầu chờ: status_resolve = 'pending' HOẶC NULL
    res = supabase.table("requests")\
        .select("*, devices(device_name, device_code, status, device_price, description, rooms(room_name)), users!requests_created_by_fkey(full_name)")\
        .or_("status_resolve.eq.pending,status_resolve.is.null")\
        .order("created_at", desc=True).execute()
    return res.data

@router.get("/my-history")
async def get_my_requests(user: dict = Depends(get_current_user)):
    res = supabase.table("requests").select("*, devices(device_name, device_code, status, device_price, description, rooms(room_name)), users!requests_created_by_fkey(full_name)")\
        .eq("created_by", user.get("user_id")).order("created_at", desc=True).execute()
    return res.data

@router.get("/all")
async def get_all_requests(user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).lower()
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ Admin mới có quyền xem toàn bộ yêu cầu")
    
    res = supabase.table("requests").select("*, devices(device_name, device_code, status, device_price, description, rooms(room_name)), users!requests_created_by_fkey(full_name)")\
        .order("created_at", desc=True).execute()
    return res.data

@router.put("/{request_id}/resolve")
async def resolve_request(request_id: int, status: str, user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).lower()
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền xử lý yêu cầu")
    
    update_resolve_data = {
        "status_resolve": status,
        "resolved_by": user.get("user_id"),
        "resolved_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
    }
    
    # Lấy thông tin yêu cầu hiện tại để lấy ID người gửi
    request_info = supabase.table("requests").select("*, devices(device_name)").eq("id", request_id).execute()
    
    if not request_info.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
        
    req = request_info.data[0]
    sender_id = req["created_by"]
    device_name = req.get("devices", {})
    if device_name is None:
        device_name = "Thiết bị"
    elif isinstance(device_name, dict):
        device_name = device_name.get("device_name", "Thiết bị")

    req_type = req.get("request_type", "REPORT")
    if req_type == "UPDATE_USER":
        req_type_label = "Cập nhật thông tin cá nhân"
    else:
        req_type_label = "Báo hỏng" if req_type == "REPORT" else "Sửa đổi/Xóa thiết bị"

    if status == "approved":
        dev_id = req["device_id"]
        req_type = req.get("request_type", "REPORT")
        
        if req_type == "DELETE":
            # Lấy đầy đủ thông tin thiết bị TRƯỚC KHI XÓA để lưu vào lịch sử
            dev_info_res = supabase.table("devices").select("*, rooms(room_name), categories(category_name)").eq("id", dev_id).execute()
            dev_info = dev_info_res.data[0] if dev_info_res.data else {}
            
            # Lưu snapshot thông tin thiết bị vào update_payload để giữ lịch sử
            device_snapshot = {
                "_deleted": True,
                "_device_name": dev_info.get("device_name", device_name),
                "_device_code": dev_info.get("device_code", "N/A"),
                "_room_name": (dev_info.get("rooms") or {}).get("room_name", "N/A"),
                "_category": (dev_info.get("categories") or {}).get("category_name", "N/A"),
                "_deleted_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
            }
            update_resolve_data["update_payload"] = device_snapshot

            # Tiến hành xóa thiết bị (device_id trong requests sẽ thành NULL nhờ ON DELETE SET NULL)
            supabase.table("devices").delete().eq("id", dev_id).execute()

        elif req_type == "UPDATE":
            payload = req.get("update_payload")
            if payload:
                valid_fields = ["device_name", "device_code", "room_id", "status", "category_id", "description", "device_price"]
                filtered_payload = {k: v for k, v in payload.items() if k in valid_fields}
                
                if "room_name" in payload and "room_id" not in filtered_payload:
                    r_res = supabase.table("rooms").select("id").eq("room_name", payload["room_name"]).execute()
                    if r_res.data: filtered_payload["room_id"] = r_res.data[0]["id"]
                
                if "category" in payload and "category_id" not in filtered_payload:
                    c_res = supabase.table("categories").select("id").eq("category_name", payload["category"]).execute()
                    if c_res.data: filtered_payload["category_id"] = c_res.data[0]["id"]

                if filtered_payload:
                    filtered_payload["updated_at"] = (datetime.utcnow() + timedelta(hours=7)).isoformat()
                    supabase.table("devices").update(filtered_payload).eq("id", dev_id).execute()

        elif req_type == "UPDATE_USER":
            payload = req.get("update_payload")
            if payload:
                payload["updated_at"] = (datetime.utcnow() + timedelta(hours=7)).isoformat()
                supabase.table("users").update(payload).eq("id", sender_id).execute()

        else:  # REPORT (Báo hỏng)
            new_status = req.get("status_device")
            if not new_status or new_status == "pending" or new_status == "":
                new_status = "Hỏng"
            
            supabase.table("devices").update({"status": new_status, "updated_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()}).eq("id", dev_id).execute()

    # THÔNG BÁO CHO NGƯỜI GỬI (Chỉ gửi nếu người gửi không phải là chính Admin đang duyệt)
    if sender_id != user.get("user_id"):
        status_label = "PHÊ DUYỆT" if status == "approved" else "TỪ CHỐI"
        if req_type == "UPDATE_USER":
            content_msg = f"Admin đã {status_label.lower()} yêu cầu {req_type_label.lower()} của bạn."
        else:
            content_msg = f"Admin đã {status_label.lower()} yêu cầu {req_type_label.lower()} của bạn cho thiết bị: {device_name}"
            
        create_notification(
            user_id=sender_id,
            title=f"Yêu cầu của bạn đã được {status_label}",
            content=content_msg,
            link="/requests",
            created_by=user.get("user_id")
        )

    res = supabase.table("requests").update(update_resolve_data).eq("id", request_id).execute()
    return res.data[0] if res.data else None
=======
from fastapi import APIRouter, Depends, HTTPException
from core.config import supabase
from services.auth_service import get_current_user
from schemas.request import RequestCreate
from datetime import datetime, timedelta
from api.routers.notifications import create_notification

router = APIRouter()

@router.post("")
async def create_request(req: RequestCreate, user: dict = Depends(get_current_user)):
    try:
        # TÌM ID THIẾT BỊ TỪ DEVICE_CODE
        dev_res = supabase.table("devices").select("id, device_name, device_code, rooms(room_name)").eq("device_code", req.device_code).execute()
        if not dev_res.data:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy thiết bị có mã: {req.device_code}")
        
        device_id = dev_res.data[0]["id"]

        # Xác định trạng thái thiết bị mong muốn
        intended_status = req.status_device
        if req.request_type == "REPORT" and (not intended_status or intended_status == "pending"):
            intended_status = "Hỏng"

        request_data = {
            "device_id": device_id,
            "created_by": user.get("user_id"),
            "description": req.description,
            "status_device": intended_status if intended_status else "pending",
            "status_resolve": "pending", # Trỏ pending vào status_resolve theo yêu cầu
            "request_type": req.request_type,
            "update_payload": req.update_payload,
            "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
        }
        
        print(f"DEBUG: Maintenance Request Data: {request_data}")
        res = supabase.table("requests").insert(request_data).execute()
        print(f"DEBUG: Supabase Request Insert Response: {res}")
        
        if res.data:
            # THÔNG BÁO CHO ADMIN (Chỉ gửi nếu người tạo KHÔNG PHẢI là admin)
            if user.get("role") != "admin":
                try:
                    admins = supabase.table("users").select("id").eq("role", "admin").execute()
                    notif_link = "/requests?tab=advanced" if req.request_type != "REPORT" else "/requests"
                    for admin in admins.data:
                        # Không gửi thông báo cho chính mình nếu mình là admin (đã check ở trên nhưng check lại cho chắc)
                        if admin["id"] != user.get("user_id"):
                            device_info = dev_res.data[0]
                            d_name = device_info.get("device_name", "N/A")
                            d_code = device_info.get("device_code", "N/A")
                            r_name = "Phòng không xác định"
                            if device_info.get("rooms"):
                                r_name = device_info["rooms"].get("room_name", "Phòng không xác định")

                            role_str = "Giáo viên" if str(user.get("role")) == "teacher" else "Admin"
                            req_type_vi = ""
                            if req.request_type == "REPORT": req_type_vi = "báo cáo trạng thái"
                            elif req.request_type == "UPDATE": req_type_vi = "sửa thông tin"
                            elif req.request_type == "DELETE": req_type_vi = "xóa"
                            else: req_type_vi = "xử lý"

                            create_notification(
                                user_id=admin["id"],
                                title="Yêu cầu mới cần phê duyệt",
                                content=f"{role_str} {user.get('full_name')} yêu cầu {req_type_vi} thiết bị {d_name} ({d_code}) tại {r_name}",
                                link=notif_link,
                                created_by=user.get("user_id")
                            )
                except Exception as e_notif:
                    print(f"DEBUG: Notification failed but request saved: {str(e_notif)}")
        
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"DEBUG: Error in create_request: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/pending")
async def get_pending_requests(user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).lower()
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền xem yêu cầu")
    
    # Lấy các yêu cầu chờ: status_resolve = 'pending' HOẶC NULL
    res = supabase.table("requests")\
        .select("*, devices(device_name, device_code, status, device_price, description, rooms(room_name)), users!requests_created_by_fkey(full_name)")\
        .or_("status_resolve.eq.pending,status_resolve.is.null")\
        .order("created_at", desc=True).execute()
    return res.data

@router.get("/my-history")
async def get_my_requests(user: dict = Depends(get_current_user)):
    res = supabase.table("requests").select("*, devices(device_name, device_code, status, device_price, description, rooms(room_name)), users!requests_created_by_fkey(full_name)")\
        .eq("created_by", user.get("user_id")).order("created_at", desc=True).execute()
    return res.data

@router.get("/all")
async def get_all_requests(user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).lower()
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ Admin mới có quyền xem toàn bộ yêu cầu")
    
    res = supabase.table("requests").select("*, devices(device_name, device_code, status, device_price, description, rooms(room_name)), users!requests_created_by_fkey(full_name)")\
        .order("created_at", desc=True).execute()
    return res.data

@router.put("/{request_id}/resolve")
async def resolve_request(request_id: int, status: str, user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).lower()
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin mới có quyền xử lý yêu cầu")
    
    update_resolve_data = {
        "status_resolve": status,
        "resolved_by": user.get("user_id"),
        "resolved_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
    }
    
    # Lấy thông tin yêu cầu hiện tại để lấy ID người gửi
    request_info = supabase.table("requests").select("*, devices(device_name)").eq("id", request_id).execute()
    
    if not request_info.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
        
    req = request_info.data[0]
    sender_id = req["created_by"]
    device_name = req.get("devices", {})
    if device_name is None:
        device_name = "Thiết bị"
    elif isinstance(device_name, dict):
        device_name = device_name.get("device_name", "Thiết bị")

    req_type = req.get("request_type", "REPORT")
    if req_type == "UPDATE_USER":
        req_type_label = "Cập nhật thông tin cá nhân"
    else:
        req_type_label = "Báo hỏng" if req_type == "REPORT" else "Sửa đổi/Xóa thiết bị"

    if status == "approved":
        dev_id = req["device_id"]
        req_type = req.get("request_type", "REPORT")
        
        if req_type == "DELETE":
            # Lấy đầy đủ thông tin thiết bị TRƯỚC KHI XÓA để lưu vào lịch sử
            dev_info_res = supabase.table("devices").select("*, rooms(room_name), categories(category_name)").eq("id", dev_id).execute()
            dev_info = dev_info_res.data[0] if dev_info_res.data else {}
            
            # Lưu snapshot thông tin thiết bị vào update_payload để giữ lịch sử
            device_snapshot = {
                "_deleted": True,
                "_device_name": dev_info.get("device_name", device_name),
                "_device_code": dev_info.get("device_code", "N/A"),
                "_room_name": (dev_info.get("rooms") or {}).get("room_name", "N/A"),
                "_category": (dev_info.get("categories") or {}).get("category_name", "N/A"),
                "_deleted_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
            }
            update_resolve_data["update_payload"] = device_snapshot

            # Tiến hành xóa thiết bị (device_id trong requests sẽ thành NULL nhờ ON DELETE SET NULL)
            supabase.table("devices").delete().eq("id", dev_id).execute()

        elif req_type == "UPDATE":
            payload = req.get("update_payload")
            if payload:
                valid_fields = ["device_name", "device_code", "room_id", "status", "category_id", "description", "device_price"]
                filtered_payload = {k: v for k, v in payload.items() if k in valid_fields}
                
                if "room_name" in payload and "room_id" not in filtered_payload:
                    r_res = supabase.table("rooms").select("id").eq("room_name", payload["room_name"]).execute()
                    if r_res.data: filtered_payload["room_id"] = r_res.data[0]["id"]
                
                if "category" in payload and "category_id" not in filtered_payload:
                    c_res = supabase.table("categories").select("id").eq("category_name", payload["category"]).execute()
                    if c_res.data: filtered_payload["category_id"] = c_res.data[0]["id"]

                if filtered_payload:
                    filtered_payload["updated_at"] = (datetime.utcnow() + timedelta(hours=7)).isoformat()
                    supabase.table("devices").update(filtered_payload).eq("id", dev_id).execute()

        elif req_type == "UPDATE_USER":
            payload = req.get("update_payload")
            if payload:
                payload["updated_at"] = (datetime.utcnow() + timedelta(hours=7)).isoformat()
                supabase.table("users").update(payload).eq("id", sender_id).execute()

        else:  # REPORT (Báo hỏng)
            new_status = req.get("status_device")
            if not new_status or new_status == "pending" or new_status == "":
                new_status = "Hỏng"
            
            supabase.table("devices").update({"status": new_status, "updated_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()}).eq("id", dev_id).execute()

    # THÔNG BÁO CHO NGƯỜI GỬI (Chỉ gửi nếu người gửi không phải là chính Admin đang duyệt)
    if sender_id != user.get("user_id"):
        status_label = "PHÊ DUYỆT" if status == "approved" else "TỪ CHỐI"
        if req_type == "UPDATE_USER":
            content_msg = f"Admin đã {status_label.lower()} yêu cầu {req_type_label.lower()} của bạn."
        else:
            content_msg = f"Admin đã {status_label.lower()} yêu cầu {req_type_label.lower()} của bạn cho thiết bị: {device_name}"
            
        create_notification(
            user_id=sender_id,
            title=f"Yêu cầu của bạn đã được {status_label}",
            content=content_msg,
            link="/requests",
            created_by=user.get("user_id")
        )

    res = supabase.table("requests").update(update_resolve_data).eq("id", request_id).execute()
    return res.data[0] if res.data else None
>>>>>>> 9082611 (update_20_6)
