import requests
import json
from datetime import datetime, timedelta
import time
import os


INTERVAL = 300   # 清理多久之前的数据（分钟）
SIZE = 10  # 可用空间和总空间容量差多少就执行循环清理（GB）


def get_access_token(refresh_token):
    """获取 access token"""
    token_url = "https://api.aliyundrive.com/v2/account/token"
    token_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    response = requests.post(token_url, json=token_data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise ValueError("获取 access token 失败")

def get_drive_id(header):
    """获取 drive_id"""
    drive_info_url = "https://user.aliyundrive.com/v2/user/get"
    response = requests.post(drive_info_url, headers=header, json={})
    if response.status_code == 200:
        is_backup = is_backup_folder()
        drive_id = response.json().get("backup_drive_id" if is_backup else "resource_drive_id")
        if drive_id:
            return drive_id
        else:
            raise ValueError("获取drive_id失败")
    else:
        response.raise_for_status()  # 抛出异常


def is_backup_folder():
    folder_type = read_file('folder_type.txt')
    if folder_type == "b":
      return True
    else:
      return False

def capacity(header):
    url = "https://api.aliyundrive.com/adrive/v1/user/getUserCapacityInfo"
    response = requests.post(url, headers=header)
    if response.status_code != 200:
        print(f"获取空间容量失败")
        return None
    drive_capacity_details = response.json().get("drive_capacity_details") 
    if drive_capacity_details.get("drive_used_size") >= drive_capacity_details.get("drive_total_size") - SIZE*1024*1024*1024:
      return False
    return True

def get_raw_list(header, drive_id, file_id, attempts=0, max_attempts=3):
    """获取转存空间文件"""
    list_url = "https://api.aliyundrive.com/adrive/v2/file/list"
    list_data = {
        "drive_id": drive_id,
        "parent_file_id": file_id,
        "updated_at": "2024-01-01T00:00:00",
        "order_direction": "ASC",
        "limit": 20
    }
    response = requests.post(list_url, headers=header, json=list_data)
    if response.status_code != 200 or "items" not in response.json():
        print(f"获取文件列表失败：folder_id={file_id}, drive_id={drive_id}")
        print(f"响应数据：{response.text}")
        print('重新获取...')
        time.sleep(2)
        if attempts >= max_attempts:
          return {}
        else:
          return get_raw_list(header, drive_id, file_id, attempts + 1, max_attempts)
    return response.json()

def convert_utc_to_beijing(utc_time_str):
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    beijing_time = utc_time + timedelta(hours=8)
    return beijing_time.timestamp()

def get_file_info(data):
    files_info = []
    for item in data.get('items', []):
        if 'file_id' in item and 'updated_at' in item:
            updated_at_timestamp = convert_utc_to_beijing(item['updated_at'])
            file_info = {
                'file_id': item['file_id'],
                'name': item['name'],
                'updated_at': updated_at_timestamp  # 转换时间
            }
            files_info.append(file_info)

    return files_info

def delete_file(header, drive_id, file_id, file_name):
    delete_url = "https://api.aliyundrive.com/v3/batch"
    body = {
        "requests": [
            {
                "body": {
                    "drive_id": drive_id,
                    "file_id": file_id
                },
                "headers": {
                    "Content-Type": "application/json"
                },
                "id": file_id,
                "method": "POST",
                "url": "/file/delete"
            }
        ],
        "resource": "file"
    }
    response = requests.post(delete_url, headers=header, json=body)
    if response.status_code == 200:
        return True
    else:
        return False


def is_older_than_seconds(update_time_timestamp, seconds):
    current_time = datetime.now().timestamp()
    time_threshold = current_time - seconds
    return update_time_timestamp < time_threshold

def read_file(filename):
    try:
      script_dir = os.path.dirname(os.path.realpath(__file__))
      file_path = os.path.join(script_dir, filename)
      with open(file_path, 'r') as file:
        first_line = file.readline().strip()
        return first_line
    except FileNotFoundError:
      print(f"文件 {file_path} 未找到。")
    except Exception as e:
      print(f"读取文件时出错：{e}")


def cycle_delete_files(files):
    sorted_files = sorted(files, key=lambda x: x['updated_at'])
    de_files = sorted_files[:3]
    print(f'---开始循环删除文件---')
    for file_info in de_files:
        file_id = file_info['file_id']
        file_name = file_info['name']
        updated_at = file_info['updated_at']
        if delete_file(header, drive_id, file_id, file_name):
            print(f"成功删除文件：{file_name}")
        else:
            print(f"删除文件失败：{file_name}")
    print(f'---执行完毕---')


refresh_token = read_file('mytoken.txt')
parent_file_id = read_file('temp_transfer_folder_id.txt')

access_token = get_access_token(refresh_token)
header = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
drive_id = get_drive_id(header)

raw_list = get_raw_list(header, drive_id, parent_file_id)
files = get_file_info(raw_list)
print(f"转存文件列表：{files}")

while True:
    cap = capacity(header)
    print(f'容量可用情况：{cap}')
    if cap is None or cap is True:  
        break 
    cycle_delete_files(files)
    raw_list = get_raw_list(header, drive_id, parent_file_id)
    files = get_file_info(raw_list)
    time.sleep(30)

for file_info in files:
    print(file_info)
    file_id = file_info['file_id']
    file_name = file_info['name']
    updated_at = file_info['updated_at']
    if is_older_than_seconds(updated_at, INTERVAL*60):
      if delete_file(header, drive_id, file_id, file_name):
          print(f"成功删除文件：{file_name}")
      else:
          print(f"删除文件失败：{file_name}")
    else:
      print(f"没超过时间，不删除：{file_name}")