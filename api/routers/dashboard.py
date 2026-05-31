from fastapi import APIRouter, Depends
from core.config import supabase
from services.auth_service import get_current_user
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/activity")
async def get_recent_activity(user: dict = Depends(get_current_user)):
    # 1. Lấy 5 lượt quét kiểm kê gần đây
    inventory_logs = supabase.table("inventory_logs").select("*, devices(device_name), users!inventory_logs_resolved_by_fkey(full_name)").order("inventory_at", desc=True).limit(5).execute()
    
    # 2. Lấy 5 báo hỏng gần đây (từ bảng requests)
    report_logs = supabase.table("requests").select("*, devices(device_name), users!requests_created_by_fkey(full_name)").eq("request_type", "REPORT").order("created_at", desc=True).limit(5).execute()
    
    # 3. Lấy 5 thiết bị mới thêm gần đây
    new_devices = supabase.table("devices").select("*, rooms(room_name)").order("created_at", desc=True).limit(5).execute()

    activities = []

    for log in inventory_logs.data:
        activities.append({
            "type": "inventory",
            "title": "Kiểm kê thiết bị",
            "content": f"Thiết bị: {log['devices']['device_name']} - Trạng thái: {log['status_at_scan']}",
            "time": log["inventory_at"],
            "user": log.get("users", {}).get("full_name", "N/A") if log.get("users") else "N/A"
        })

    for log in report_logs.data:
        activities.append({
            "type": "report",
            "title": "Báo hỏng mới",
            "content": f"Thiết bị: {log.get('devices', {}).get('device_name', 'N/A')} - Vấn đề: {log.get('description', 'Chưa có mô tả')}",
            "time": log["created_at"],
            "user": log.get("users", {}).get("full_name", "N/A") if log.get("users") else "N/A"
        })

    for dev in new_devices.data:
        activities.append({
            "type": "device",
            "title": "Tài sản mới",
            "content": f"Đã thêm {dev['device_name']} vào phòng {dev['rooms']['room_name']}",
            "time": dev["created_at"],
            "user": "Hệ thống"
        })


@router.get("/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    user_role = user.get("role", "teacher")
    user_id = user.get("user_id")
    room_id = user.get("room_id")

    if user_role == "admin":
        # Logic cho Admin: Lấy toàn bộ hệ thống
        total_devices = supabase.table("devices").select("id", count="exact").execute().count
        total_rooms = supabase.table("rooms").select("id", count="exact").execute().count
        
        # Đếm yêu cầu chờ: status_resolve = 'pending' HOẶC NULL
        pending_res = supabase.table("requests").select("id", count="exact").or_("status_resolve.eq.pending,status_resolve.is.null").execute()
        pending_requests = pending_res.count
        
        broken_devices = supabase.table("devices").select("id", count="exact").ilike("status", "%Hỏng%").execute().count
        good_devices = supabase.table("devices").select("id", count="exact").ilike("status", "%Tốt%").execute().count
        need_maintenance_devices = supabase.table("devices").select("id", count="exact").ilike("status", "%Cần bảo trì%").execute().count
        maintenance_devices = supabase.table("devices").select("id", count="exact").ilike("status", "%Đang bảo trì%").execute().count
    else:
        # Logic cho Giáo viên: Chỉ lấy dữ liệu trong phòng được phân công
        if not room_id:
            return {
                "total_devices": 0, "total_rooms": 0, "pending_requests": 0,
                "broken_devices": 0, "good_devices": 0, "need_maintenance_devices": 0, "maintenance_devices": 0
            }
            
        total_devices = supabase.table("devices").select("id", count="exact").eq("room_id", room_id).execute().count
        total_rooms = 1
        # Yêu cầu chờ của giáo viên: status_resolve = 'pending' HOẶC NULL
        pending_res = supabase.table("requests").select("id", count="exact").eq("created_by", user_id).or_("status_resolve.eq.pending,status_resolve.is.null").execute()
        pending_requests = pending_res.count
        
        broken_devices = supabase.table("devices").select("id", count="exact").eq("room_id", room_id).ilike("status", "%Hỏng%").execute().count
        good_devices = supabase.table("devices").select("id", count="exact").eq("room_id", room_id).ilike("status", "%Tốt%").execute().count
        need_maintenance_devices = supabase.table("devices").select("id", count="exact").eq("room_id", room_id).ilike("status", "%Cần bảo trì%").execute().count
        maintenance_devices = supabase.table("devices").select("id", count="exact").eq("room_id", room_id).ilike("status", "%Đang bảo trì%").execute().count

    return {
        "total_devices": total_devices or 0,
        "total_rooms": total_rooms or 0,
        "pending_requests": pending_requests or 0,
        "broken_devices": broken_devices or 0,
        "good_devices": good_devices or 0,
        "need_maintenance_devices": need_maintenance_devices or 0,
        "maintenance_devices": maintenance_devices or 0
    }
