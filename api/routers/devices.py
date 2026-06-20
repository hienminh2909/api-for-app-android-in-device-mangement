import io
import time
import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
import pandas as pd
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from typing import List, Optional

from core.config import supabase
from services.auth_service import get_current_user
from schemas.device import DeviceResponse, RegisterDevice, DeviceUpdate
from api.routers.notifications import create_notification

router = APIRouter()

def get_safe_url(bucket, path):
    try:
        res = supabase.storage.from_(bucket).get_public_url(path)
        if isinstance(res, str): return res
        return getattr(res, "public_url", str(res))
    except:
        from core.config import SUPABASE_URL
        return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"

@router.get("", response_model=List[DeviceResponse])
async def get_devices(
    category_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    ids: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    role = user.get("role")
    user_room_id = user.get("room_id")

    query = supabase.table("devices").select("*, rooms(id, room_name), categories(category_name), users(full_name)")

    if role == "teacher":
        if user_room_id is None: 
            return []
        query = query.eq("room_id", user_room_id)

    if status and status.strip():
        query = query.eq("status", status)

    if category_id:
        query = query.eq("category_id", category_id)

    if search and search.strip():
        val = f"%{search}%"
        room_ids_res = supabase.table("rooms").select("id").ilike("room_name", val).execute()
        room_ids = [str(r['id']) for r in room_ids_res.data]
        if room_ids:
            room_filter = f"room_id.in.({','.join(room_ids)})"
            query = query.or_(f"device_name.ilike.{val},device_code.ilike.{val},{room_filter}")
        else:
            query = query.or_(f"device_name.ilike.{val},device_code.ilike.{val}")

    if ids and ids.strip():
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if id_list:
            query = query.in_("id", id_list)

    response = query.order("created_at", desc=True).execute()
    
    if not response.data:
        return []
    
    results = []
    for item in response.data:
        room_obj = item.get("rooms") or {"room_name": "N/A"}
        cat_obj = item.get("categories") or {"category_name": "N/A"}
        user_obj = item.get("users") or {"full_name": "N/A"}
        
        item["rooms"] = room_obj
        item["categories"] = cat_obj
        item["users"] = user_obj
        item["quantity"] = 1
        item["all_devices_detail"] = []
        results.append(item)
        
    return results

@router.get("/summary", response_model=List[DeviceResponse])
async def get_devices_summary(
    category_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    ids: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    role = user.get("role")
    user_room_id = user.get("room_id")

    query = supabase.table("devices").select("*, rooms(id, room_name), categories(category_name), users(full_name)")

    if role == "teacher":
        if user_room_id is None: 
            return []
        query = query.eq("room_id", user_room_id)

    if status and status.strip():
        query = query.eq("status", status)

    if category_id:
        query = query.eq("category_id", category_id)

    if search and search.strip():
        val = f"%{search}%"
        room_ids_res = supabase.table("rooms").select("id").ilike("room_name", val).execute()
        room_ids = [str(r['id']) for r in room_ids_res.data]
        if room_ids:
            room_filter = f"room_id.in.({','.join(room_ids)})"
            query = query.or_(f"device_name.ilike.{val},device_code.ilike.{val},{room_filter}")
        else:
            query = query.or_(f"device_name.ilike.{val},device_code.ilike.{val}")

    if ids and ids.strip():
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if id_list:
            query = query.in_("id", id_list)

    response = query.order("created_at", desc=True).execute()
    
    if not response.data:
        return []

    raw_data = response.data
    grouped_data = {}

    for item in raw_data:
        room_obj = item.get("rooms") or {"room_name": "N/A"}
        cat_obj = item.get("categories") or {"category_name": "N/A"}
        user_obj = item.get("users") or {"full_name": "N/A"}
        
        room_n = room_obj.get("room_name", "N/A")
        cat_n = cat_obj.get("category_name", "N/A")
        price_n = str(item.get("device_price") or "0")
        date_n = str(item.get("purchase_date") or "N/A")
        desc_n = str(item.get("description") or "").strip()
        
        group_key = f"{item['device_name']}-{room_n}-{cat_n}-{item['status']}-{price_n}-{date_n}-{desc_n}"
        
        current_device_detail = {
            "id": item["id"],
            "device_code": item["device_code"],
            "qr_url": item.get("qr_url"),
        }

        if group_key not in grouped_data:
            new_item = item.copy()
            new_item["quantity"] = 1
            new_item["all_devices_detail"] = [current_device_detail]
            new_item["rooms"] = room_obj
            new_item["categories"] = cat_obj
            new_item["users"] = user_obj
            new_item["image_url"] = item.get("image_url")
            grouped_data[group_key] = new_item
        else:
            grouped_data[group_key]["quantity"] += 1
            grouped_data[group_key]["all_devices_detail"].append(current_device_detail)
            if not grouped_data[group_key].get("image_url") and item.get("image_url"):
                grouped_data[group_key]["image_url"] = item.get("image_url")

    return list(grouped_data.values())

@router.post("")
async def register_device(
    device_name: str = Form(...),
    room_name: str = Form(...),
    category_name: str = Form(...),
    status: str = Form(...),
    description: Optional[str] = Form(None),
    purchase_date: Optional[str] = Form(None),
    device_price: Optional[str] = Form(None),
    quantity: int = Form(1),
    image: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user)
):
    try:
        # 0. Xử lý ảnh nếu có
        image_url = None
        if image:
            file_ext = image.filename.split(".")[-1]
            file_name = f"dev_{int(time.time())}.{file_ext}"
            file_content = await image.read()
            
            supabase.storage.from_("image_device").upload(
                path=file_name,
                file=file_content,
                file_options={"content-type": image.content_type}
            )
            image_url = get_safe_url("image_device", file_name)

        # 1. Xử lý tự động tạo phòng nếu chưa có
        room_name_clean = room_name.strip()
        room_res = supabase.table("rooms").select("id").eq("room_name", room_name_clean).execute()
        
        if room_res.data:
            r_id = room_res.data[0]['id']
        else:
            new_room = supabase.table("rooms").insert({"room_name": room_name_clean}).execute()
            if not new_room.data:
                raise HTTPException(status_code=400, detail="Không thể tạo phòng mới")
            r_id = new_room.data[0]['id']
        
        cat_res = supabase.table("categories").select("id, category_code").eq("category_name", category_name).execute()
        if not cat_res.data:
            raise HTTPException(status_code=404, detail="Loại thiết bị không tồn tại")       
        
        category_id = cat_res.data[0]['id']
        category_code = cat_res.data[0]['category_code']

        # Chuẩn hóa giá tiền: Loại bỏ dấu chấm/phẩy trước khi lưu
        clean_price = 0
        if device_price:
            try:
                clean_price = float(str(device_price).replace(".", "").replace(",", ""))
            except:
                clean_price = 0

        qty = quantity if quantity > 0 else 1
        base_ts = int(time.time())
        devices_to_insert = []

        for i in range(qty):
            suffix = i + 1
            dev_code = f"{room_name_clean.replace(' ', '')}-{category_code}-{base_ts}-{suffix}"
            
            qr_url = f"/api/web/devices/qr/{dev_code}"
            bar_url = f"/api/web/devices/barcode/{dev_code}"
            
            devices_to_insert.append({
                "device_name": device_name,
                "device_code": dev_code,
                "room_id": r_id,
                "category_id": category_id,
                "status": status,
                "description": description,
                "purchase_date": purchase_date,
                "qr_url": qr_url,
                "barcode_url": bar_url,
                "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat(),
                "created_by": user.get("user_id"),
                "device_price": clean_price,
                "image_url": image_url
            })
        
        res = supabase.table("devices").insert(devices_to_insert).execute()
        
        if not res.data:
            raise HTTPException(status_code=500, detail="Không thể lưu thiết bị vào cơ sở dữ liệu")

        return {
            "message": f"Đã đăng ký thành công {len(res.data)} thiết bị",
            "count": len(res.data),
            "ids": [d['id'] for d in res.data],
            "device_codes": [d.get('device_code') for d in res.data],
            "qr_urls": [d.get('qr_url') for d in res.data],
            "image_url": image_url
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/validate")
async def validate_import(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        if df.empty:
            raise HTTPException(status_code=400, detail="File rỗng")

        rooms_data = supabase.table("rooms").select("id, room_name").execute().data
        cats_data = supabase.table("categories").select("id, category_name").execute().data
        
        room_names = {r['room_name'] for r in rooms_data}
        cat_names = {c['category_name'] for c in cats_data}

        preview_data = []
        for index, row in df.iterrows():
            d_name = str(row.get('device_name', '')).strip()
            r_name = str(row.get('room_name', '')).strip()
            c_name = str(row.get('category_name', '')).strip()
            qty = int(row.get('quantity', 1))
            d_price = str(row.get('device_price', '')).strip()
            p_date = str(row.get('purchase_date', '')).strip()

            error_msg = []
            room_err = r_name not in room_names
            cat_err = c_name not in cat_names
            
            if room_err: error_msg.append(f"Phòng '{r_name}' không tồn tại")
            if cat_err: error_msg.append(f"Danh mục '{c_name}' không tồn tại")
            if not d_name or d_name == 'nan': error_msg.append("Thiết bị không có tên")
            if not d_price or d_price == 'nan': error_msg.append("Thiếu giá tiền")
            if not p_date or p_date == 'nan': error_msg.append("Thiếu ngày mua")

            preview_data.append({
                "device_name": d_name,
                "room_name": r_name,
                "category_name": c_name,
                "quantity": qty,
                "device_price": d_price,
                "purchase_date": p_date,
                "description": str(row.get('description', '')).strip(),
                "room_error": room_err,
                "cat_error": cat_err,
                "error_msg": error_msg
            })

            # Check thêm mô tả
            if not str(row.get('description', '')).strip() or str(row.get('description', '')) == 'nan':
                error_msg.append("Thiếu mô tả thiết bị")
                preview_data[-1]["is_valid"] = False # Đánh dấu không hợp lệ
            
            preview_data[-1]["is_valid"] = len(error_msg) == 0

        return {"status": "success", "data": preview_data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/template")
async def download_template():
    try:
        # Tạo file mẫu với các cột yêu cầu (V2)
        columns = [
            "device_name", "room_name", "category_name", 
            "status", "device_price", "quantity", "purchase_date", "description"
        ]
        # Dữ liệu mẫu (ví dụ)
        example_data = [{
            "device_name": "Máy tính Dell Latitude 7490",
            "room_name": "Phòng 101",
            "category_name": "Máy tính",
            "status": "Tốt",
            "device_price": "12.500.000",
            "quantity": 1,
            "purchase_date": datetime.now().strftime("%Y-%m-%d"),
            "description": "Máy tính xách tay i5 8th Gen, 8GB RAM, 256GB SSD"
        }]
        
        df = pd.DataFrame(example_data, columns=columns)
        output = io.BytesIO()
        with pd.ExcelWriter(output) as writer:
            df.to_excel(writer, index=False, sheet_name='Template_V2')
        
        output.seek(0)
        data = output.getvalue()
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=Mau_Nhap_Thiet_Bi_Moi_{int(time.time())}.xlsx",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_and_register(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        if df.empty:
            raise HTTPException(status_code=400, detail="File rỗng")

        devices_to_insert = []
        base_ts = int(time.time())

        rooms_data = supabase.table("rooms").select("id, room_name").execute().data
        cats_data = supabase.table("categories").select("id, category_name, category_code").execute().data
        
        room_map = {r['room_name']: r['id'] for r in rooms_data}
        cat_map = {c['category_name']: {'id': c['id'], 'code': c['category_code']} for c in cats_data}

        for index, row in df.iterrows():
            d_name = str(row.get('device_name', ''))
            r_name = str(row.get('room_name', ''))
            c_name = str(row.get('category_name', ''))
            qty = int(row.get('quantity', 1))
            d_price = str(row.get('device_price', ''))
            p_date = str(row.get('purchase_date', ''))
            description = str(row.get('description', ''))

            if r_name not in room_map or c_name not in cat_map:
                continue
            
            # Nếu thiếu mô tả hoặc giá thì bỏ qua (hoặc log lỗi)
            if not description or description == 'nan' or not d_price or d_price == 'nan':
                continue

            r_id = room_map[r_name]
            c_id = cat_map[c_name]['id']
            c_code = cat_map[c_name]['code']

            # Chuẩn hóa giá tiền từ Excel
            clean_price = 0
            try:
                # Loại bỏ dấu chấm và phẩy, ép về float
                clean_price = float(str(d_price).replace(".", "").replace(",", ""))
            except:
                clean_price = 0

            for i in range(qty):
                dev_code = f"{r_name.replace(' ', '')}-{c_code}-{base_ts}-{index}-{i+1}"
                
                qr_url = f"/api/web/devices/qr/{dev_code}"
                bar_url = f"/api/web/devices/barcode/{dev_code}"

                devices_to_insert.append({
                    "device_name": d_name, "device_code": dev_code,
                    "room_id": r_id, "category_id": c_id, "status": "Tốt",
                    "qr_url": qr_url, "barcode_url": bar_url,
                    "purchase_date": p_date if p_date != "nan" else (datetime.utcnow() + timedelta(hours=7)).isoformat(),
                    "device_price": clean_price,
                    "description": description,
                    "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat(),
                    "created_by": user.get("user_id")
                })

        res = supabase.table("devices").insert(devices_to_insert).execute()
        return {
            "status": "success",
            "ids": [d['id'] for d in res.data],
            "count": len(res.data),
            "device_codes": [d.get('device_code') for d in res.data],
            "qr_urls": [d.get('qr_url') for d in res.data]
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))   

@router.put("/{device_id}")
async def update_device(device_id: int, req: DeviceUpdate, user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).strip().lower()
    print(f"DEBUG: update_device called by user {user.get('user_id')} with role: '{user_role}'")
    
    if user_role == "admin":
        try:
            update_data = {"updated_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()}
            if req.status is not None: update_data["status"] = req.status
            if req.device_name is not None: update_data["device_name"] = req.device_name
            if req.description is not None: update_data["description"] = req.description
            if req.purchase_date is not None: update_data["purchase_date"] = req.purchase_date
            
            if req.device_price is not None:
                try:
                    # Ép kiểu giá tiền về float để tránh lỗi DB
                    update_data["device_price"] = float(str(req.device_price).replace(",", "").replace(".", ""))
                except:
                    update_data["device_price"] = req.device_price
            
            if req.room_name is not None:
                room_res = supabase.table("rooms").select("id").eq("room_name", req.room_name).execute()
                if room_res.data:
                    update_data["room_id"] = room_res.data[0]['id']
                else:
                    raise HTTPException(status_code=404, detail=f"Phòng {req.room_name} không tồn tại")
            
            if req.category is not None:
                category_res = supabase.table("categories").select("id").eq("category_name", req.category).execute()
                if category_res.data:
                    update_data["category_id"] = category_res.data[0]['id']
                else:
                    raise HTTPException(status_code=404, detail=f"Danh mục {req.category} không tồn tại")
            
            if req.rfid_tag is not None: update_data["rfid_tag"] = req.rfid_tag
            
            print(f"DEBUG: update_data to Supabase: {update_data}")
            res = supabase.table("devices").update(update_data).eq("id", device_id).execute()
            return {"message": "Cập nhật thành công!"}
        except Exception as e:
            print(f"ERROR Supabase Update: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    else:
        # USER: Tạo yêu cầu phê duyệt chỉnh sửa
        try:
            # Lấy thông tin thiết bị hiện tại
            current_dev_res = supabase.table("devices").select("*").eq("id", device_id).execute()
            if not current_dev_res.data:
                raise HTTPException(status_code=404, detail="Thiết bị không tồn tại")
            current_dev = current_dev_res.data[0]
            
            # Lấy các trường mà user truyền lên
            raw_payload = req.dict(exclude_unset=True)
            update_payload = {}
            
            def safe_str(val):
                return str(val).strip() if val is not None else ""
            
            if "status" in raw_payload and safe_str(raw_payload["status"]) != safe_str(current_dev.get("status")):
                update_payload["status"] = raw_payload["status"]
                
            if "device_name" in raw_payload and safe_str(raw_payload["device_name"]) != safe_str(current_dev.get("device_name")):
                update_payload["device_name"] = raw_payload["device_name"]
                
            if "description" in raw_payload and safe_str(raw_payload["description"]) != safe_str(current_dev.get("description")):
                update_payload["description"] = raw_payload["description"]
                
            if "device_price" in raw_payload:
                try:
                    new_price = float(str(raw_payload["device_price"]).replace(",", "").replace(".", ""))
                    old_price = float(current_dev.get("device_price") or 0)
                    if new_price != old_price:
                        update_payload["device_price"] = new_price
                except:
                    pass

            if "category" in raw_payload:
                cat_res = supabase.table("categories").select("category_name").eq("id", current_dev.get("category_id")).execute()
                current_cat = cat_res.data[0]["category_name"] if cat_res.data else ""
                if safe_str(raw_payload["category"]) != safe_str(current_cat):
                    update_payload["category"] = raw_payload["category"]
            
            if "room_name" in raw_payload:
                room_res = supabase.table("rooms").select("room_name").eq("id", current_dev.get("room_id")).execute()
                current_room = room_res.data[0]["room_name"] if room_res.data else ""
                if safe_str(raw_payload["room_name"]) != safe_str(current_room):
                    update_payload["room_name"] = raw_payload["room_name"]

            if not update_payload:
                raise HTTPException(status_code=400, detail="Không có thông tin nào được thay đổi")
            
            request_data = {
                "device_id": device_id,
                "created_by": user.get("user_id"),
                "description": f"Yêu cầu chỉnh sửa thông tin thiết bị",
                "request_type": "UPDATE",
                "update_payload": update_payload,
                "status_resolve": "pending",
                "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
            }
            supabase.table("requests").insert(request_data).execute()
            
            # Lấy thông tin thiết bị để gửi thông báo chi tiết
            dev_info_res = supabase.table("devices").select("device_name, device_code, rooms(room_name)").eq("id", device_id).execute()
            d_name = "N/A"
            d_code = "N/A"
            r_name = "Phòng không xác định"
            if dev_info_res.data:
                d_info = dev_info_res.data[0]
                d_name = d_info.get("device_name", "N/A")
                d_code = d_info.get("device_code", "N/A")
                if d_info.get("rooms"):
                    r_name = d_info["rooms"].get("room_name", "Phòng không xác định")

            role_str = "Giáo viên" if str(user.get("role")) == "teacher" else "Admin"

            # THÔNG BÁO CHO ADMIN
            try:
                admins = supabase.table("users").select("id").eq("role", "admin").execute()
                for admin in admins.data:
                    create_notification(
                        user_id=admin["id"],
                        title="Yêu cầu sửa thiết bị",
                        content=f"{role_str} {user.get('full_name')} yêu cầu sửa thông tin thiết bị {d_name} ({d_code}) tại {r_name}",
                        link="/requests?tab=advanced",
                        created_by=user.get("user_id")
                    )
            except: pass

            return {"message": "Yêu cầu chỉnh sửa đã được gửi tới Admin chờ phê duyệt"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{device_id}")
async def delete_device(device_id: int, user: dict = Depends(get_current_user)):
    user_role = str(user.get("role", "")).strip().lower()
    print(f"DEBUG: delete_device called by user {user.get('user_id')} with role: '{user_role}'")
    
    if user_role == "admin":
        try:
            res = supabase.table("devices").delete().eq("id", device_id).execute()
            if not res.data:
                raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
            return {"message": "Đã xóa thiết bị thành công"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        # USER: Tạo yêu cầu xóa chờ phê duyệt
        try:
            request_data = {
                "device_id": device_id,
                "created_by": user.get("user_id"),
                "description": "Yêu cầu xóa thiết bị khỏi hệ thống",
                "request_type": "DELETE",
                "update_payload": None,
                "status_resolve": "pending",
                "created_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
            }
            supabase.table("requests").insert(request_data).execute()
            
            # Lấy thông tin thiết bị để gửi thông báo chi tiết
            dev_info_res = supabase.table("devices").select("device_name, device_code, rooms(room_name)").eq("id", device_id).execute()
            d_name = "N/A"
            d_code = "N/A"
            r_name = "Phòng không xác định"
            if dev_info_res.data:
                d_info = dev_info_res.data[0]
                d_name = d_info.get("device_name", "N/A")
                d_code = d_info.get("device_code", "N/A")
                if d_info.get("rooms"):
                    r_name = d_info["rooms"].get("room_name", "Phòng không xác định")

            role_str = "Giáo viên" if str(user.get("role")) == "teacher" else "Admin"

            # THÔNG BÁO CHO ADMIN
            try:
                admins = supabase.table("users").select("id").eq("role", "admin").execute()
                for admin in admins.data:
                    create_notification(
                        user_id=admin["id"],
                        title="Yêu cầu xóa thiết bị",
                        content=f"{role_str} {user.get('full_name')} yêu cầu xóa thiết bị {d_name} ({d_code}) tại {r_name}",
                        link="/requests?tab=advanced",
                        created_by=user.get("user_id")
                    )
            except: pass

            return {"message": "Yêu cầu xóa đã được gửi tới Admin chờ phê duyệt"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload-image")
async def upload_device_image(
    file: UploadFile = File(...),
    device_ids: str = Form(None),
    device_name: str = Form(None),
    user: dict = Depends(get_current_user)
):
    """
    Upload ảnh thiết bị lên Supabase Storage bucket 'image_device'.
    - device_ids: danh sách ID thiết bị (phân cách bằng dấu phẩy) cần cập nhật image_url
    - device_name: tên thiết bị (dùng để đặt tên file)
    """
    try:
        # Đọc file ảnh
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="File ảnh rỗng")

        # Xác định content-type
        content_type = file.content_type or "image/png"
        
        # Tạo tên file an toàn (loại bỏ dấu tiếng Việt và ký tự đặc biệt)
        import unicodedata
        import re

        def remove_accents(input_str):
            nfkd_form = unicodedata.normalize('NFKD', input_str)
            return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

        ext = file.filename.split(".")[-1] if "." in file.filename else "png"
        raw_name = device_name or "device"
        # Loại bỏ dấu, chuyển sang lowercase, thay khoảng trắng/ký tự đặc biệt bằng gạch dưới
        safe_name = remove_accents(raw_name).lower()
        safe_name = re.sub(r'[^a-z0-9]', '_', safe_name)
        # Loại bỏ gạch dưới thừa
        safe_name = re.sub(r'_+', '_', safe_name).strip('_')
        
        timestamp = int(time.time())
        file_path = f"{safe_name}_{timestamp}.{ext}"

        # Upload lên Supabase Storage bucket 'image_device'
        try:
            supabase.storage.from_("image_device").upload(
                path=file_path,
                file=contents,
                file_options={"content-type": content_type}
            )
        except Exception as storage_err:
            print(f"STORAGE ERROR: {str(storage_err)}")
            # Nếu bucket chưa có hoặc lỗi, trả về lỗi chi tiết hơn
            raise HTTPException(status_code=500, detail=f"Lỗi Storage Supabase: {str(storage_err)}. Vui lòng kiểm tra bucket 'image_device' đã được tạo chưa?")

        # Lấy public URL
        try:
            image_url_res = supabase.storage.from_("image_device").get_public_url(file_path)
            # Một số phiên bản trả về object, một số trả về string trực tiếp
            if isinstance(image_url_res, str):
                image_url = image_url_res
            else:
                image_url = getattr(image_url_res, "public_url", str(image_url_res))
        except:
            image_url = f"{supabase_url}/storage/v1/object/public/image_device/{file_path}"

        # Cập nhật image_url cho tất cả device_ids
        if device_ids and str(device_ids).strip() != "None":
            try:
                # Xử lý chuỗi ID (ví dụ: "1,2,3")
                dids = [int(x.strip()) for x in str(device_ids).split(",") if x.strip()]
                print(f"DEBUG: Bat dau cap nhat image_url cho {len(dids)} thiet bi: {dids}")
                
                for did in dids:
                    # Thử cập nhật, nếu không thấy ID thì đợi 300ms rồi thử lại 1 lần (đề phòng race condition)
                    success = False
                    for attempt in range(2):
                        res = supabase.table("devices").update({
                            "image_url": image_url,
                            "updated_at": (datetime.utcnow() + timedelta(hours=7)).isoformat()
                        }).eq("id", did).execute()
                        
                        if res.data:
                            print(f"DEBUG: [THANH CONG] Da cap nhat device ID {did} (Lan thu {attempt + 1})")
                            success = True
                            break
                        else:
                            print(f"DEBUG: [CHO DOI] Khong tim thay ID {did}, dang thu lai...")
                            time.sleep(0.3)
                    
                    if not success:
                        print(f"DEBUG: [THAT BAI] Vinh vien khong tim thay device ID {did}")
                
            except Exception as db_err:
                print(f"DATABASE UPDATE ERROR: {str(db_err)}")
                raise HTTPException(status_code=500, detail=f"Lỗi cập nhật Database: {str(db_err)}")
        else:
            print("DEBUG: Khong co device_ids duoc gui len de cap nhat image_url")

        return {"message": "Upload ảnh thành công", "image_url": image_url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
