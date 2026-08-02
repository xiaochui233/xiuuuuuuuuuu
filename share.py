import http.server
import socketserver
import html
import os
import re
import socket
import sys
import urllib.parse
from datetime import datetime
import tqdm

PORT = 8000
QR_DARK = "█"
QR_LIGHT = " "
def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip
def find_free_port(start_port=8000, max_attempts=100):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"无法找到可用端口（从{start_port}开始尝试了{max_attempts}个端口）")
def print_terminal_qrcode(url, border=2):
    if not HAS_QRCODE:
        print("QR")
        return
    qr = qrcode.QRCode(
        version=None,        
        error_correction=qrcode.constants.ERROR_CORRECT_H, 
        box_size=1,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.modules   
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    qr_lines = []
    for r in range(rows):
        row_str = " ".join(QR_DARK if matrix[r][c] else QR_LIGHT for c in range(cols))
        qr_lines.append(row_str)
    content_width = cols * 2 - 1 if cols > 0 else 0
    padding_spaces = "  "
    inner_width = content_width + len(padding_spaces) * 2
    top_border = "┌" + "─" * inner_width + "┐"
    bottom_border = "└" + "─" * inner_width + "┘"
    empty_content_line = " " * inner_width
    print(top_border)
    print("│" + empty_content_line + "│")
    for line in qr_lines:
        print("│" + padding_spaces + line + padding_spaces + "│")
    print("│" + empty_content_line + "│")
    print(bottom_border)


class SilentHTTPRequestHandler(http.server.BaseHTTPRequestHandler):    
    def log_message(self, format, *args):
        pass
class ProgressHTTPRequestHandler(SilentHTTPRequestHandler):
    def do_GET(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            listing = os.listdir(path)
            listing.sort(key=lambda a: (not os.path.isdir(os.path.join(path, a)), a.lower()))
            lan_ip = get_lan_ip()
            lan_url = f"http://{lan_ip}:{self.server.server_address[1]}"
            html_content = f"""
          HTML
          """
            self.wfile.write(html_content.encode('utf-8'))
        else:
            try:
                file_size = os.path.getsize(path)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
                self.send_header("Content-Length", str(file_size))
                self.end_headers()
                if file_size < 10 * 1024 * 1024:
                    chunk_size = 256 * 1024
                elif file_size < 100 * 1024 * 1024:
                    chunk_size = 512 * 1024
                else:
                    chunk_size = 1024 * 1024 
                with open(path, 'rb') as f:
                    with tqdm.tqdm(total=file_size, unit='B', unit_scale=True, 
                                   desc=f"📥 下载 {os.path.basename(path)}", 
                                   ncols=72) as pbar:
                        while True:
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            pbar.update(len(chunk))
            except OSError:
                self.send_error(404, "File not found")
    def do_POST(self):
        """处理文件与文本的上传"""
        content_type = self.headers.get('Content-Type')
        if not content_type or not content_type.startswith('multipart/form-data'):
            self.send_error(400, "Bad Request")
            return
        boundary = content_type.split("boundary=")[1].encode()
        content_length = int(self.headers.get('Content-Length'))
        print(f"\n📥 正在接收数据...")
        if content_length < 10 * 1024 * 1024:
            chunk_size = 256 * 1024
        elif content_length < 100 * 1024 * 1024:
            chunk_size = 512 * 1024
        else:
            chunk_size = 1024 * 1024
        body = bytearray(content_length)
        offset = 0
        remaining = content_length
        with tqdm.tqdm(total=content_length, unit='B', unit_scale=True, 
                       desc="📥 接收数据", ncols=62) as pbar:
            while remaining > 0:
                read_size = min(remaining, chunk_size)
                chunk = self.rfile.read(read_size)
                if not chunk:
                    break
                body[offset:offset+len(chunk)] = chunk
                offset += len(chunk)
                remaining -= len(chunk)
                pbar.update(len(chunk))
        body = bytes(body[:offset])
        parts = body.split(b'--' + boundary)
        uploaded_file_data = None
        uploaded_filename = None
        text_content = None
        custom_filename = None
        for part in parts:
            if b'Content-Disposition' in part:
                header, data = part.split(b'\r\n\r\n', 1)
                data = data.rsplit(b'\r\n', 1)[0]
                header_str = header.decode('utf-8', errors='ignore')
                if 'name="file"' in header_str:
                    filename_match = re.search(r'filename="([^"]+)"', header_str)
                    if filename_match and filename_match.group(1):
                        uploaded_filename = filename_match.group(1)
                        uploaded_file_data = data
                elif 'name="filename"' in header_str:
                    custom_filename = data.decode('utf-8', errors='ignore').strip()
                elif 'name="text_content"' in header_str:
                    text_content = data.decode('utf-8', errors='ignore')
        target_dir = self.translate_path(self.path)
        if uploaded_filename and uploaded_file_data is not None:
            save_path = os.path.join(target_dir, os.path.basename(uploaded_filename))
            print(f"📝 正在保存文件: {uploaded_filename}")
            with tqdm.tqdm(total=len(uploaded_file_data), unit='B', unit_scale=True, 
                           desc="💾 写入文件", ncols=58) as pbar:
                with open(save_path, 'wb') as f:
                    f.write(uploaded_file_data)
                    pbar.update(len(uploaded_file_data))
            print(f"✅ 文件保存完成: {save_path}")
        elif text_content:
            if custom_filename:
                if not custom_filename.endswith('.txt'):
                    custom_filename += '.txt'
                final_name = custom_filename
            else:
                final_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
            save_path = os.path.join(target_dir, os.path.basename(final_name))
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
            print(f"✅ 文本已保存: {final_name} ({len(text_content)} 字符)")
        self.send_response(303)
        self.send_header('Location', self.path)
        self.end_headers()
    def translate_path(self, path):
        path = urllib.parse.unquote(path)
        return os.path.normpath(os.path.join(os.getcwd(), path.lstrip('/')))
if __name__ == "__main__":
    try:
        import tqdm
    except ImportError:
        print("TQ")
        sys.exit(1)
    if os.name == 'nt':
        os.system('mode con: cols=78 lines=46')
    actual_port = find_free_port(PORT)
    Handler = ProgressHTTPRequestHandler
    lan_ip = get_lan_ip()
    lan_url = f"http://{lan_ip}:{actual_port}"
    print("=" * 59)
    print(f"  局域网传输服务已启动！")
    print(f"  电脑访问地址：{lan_url}")
    print("=" * 57)
    print_terminal_qrcode(lan_url)
    print(f"  📱 手机扫描上方二维码即可访问")
    print("=" * 57)
    print(f"  By.hikari　　版本：1.0.0802（高速传输版）")
    print("  按 Ctrl+C 停止服务或直接关闭窗口")
    print("=" * 56)
    try:
        with socketserver.TCPServer(("", actual_port), Handler) as httpd:
            print("✅ 服务已启动，等待连接...")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n[提示] 服务已由用户手动停止 (Ctrl+C)。")
