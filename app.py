# app.py
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import subprocess
import os
import threading
from datetime import datetime
import paramiko
import zipfile
import yaml

app = Flask(__name__)
socketio = SocketIO(app)

# 修改打开文件的方式
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 配置项
LOCAL_PROJECT_ROOT = config['local_project_root']
SSH_CONFIGS = config['servers']

# 发送信息给前端
def send_message(message):
    # 判断是不是空消息, 不是的话再进行发送
    if message:
      # 在每条消息前添加时间, 格式为 YYYY-MM-DD HH:MM:SS
      socketio.emit('command_output', {'data': f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"})

# 执行本地终端命令
def execute_command(command, cwd):
    """执行命令并实时发送输出"""
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            send_message(output.strip())

    if process.returncode != 0:
        raise Exception(f"命令执行失败，退出码: {process.returncode}")

# 递归创建ZIP压缩包, 并且将压缩进度实时返回给前端
def zipdir(path, ziph):
    total_files = sum([len(files) for _, _, files in os.walk(path)])
    processed_files = 0

    # 获取dist目录的父路径用于计算相对路径
    base_path = os.path.normpath(path)

    for root, _, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            # 计算相对路径, 确保使用正斜杠(/)作为ZIP内部路径分隔符
            relative_path = os.path.relpath(file_path, start=base_path).replace(os.sep, '/')
            # 添加文件时指定arcname参数
            ziph.write(file_path, arcname=relative_path)
            processed_files += 1
            # 发送进度更新
            percent = int((processed_files / total_files) * 100)
            send_message(f'正在压缩 dist 文件，{processed_files}/{total_files} 进度：{percent}%')

# 部署到服务器
def deploy_to_server(server_name):
    """部署到指定服务器"""
    try:
        config = SSH_CONFIGS.get(server_name)

        if not config:
            raise Exception(f"服务器配置 {server_name} 不存在")

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        dist_path = os.path.join(LOCAL_PROJECT_ROOT, 'dist')
        zip_name = f"dist_{timestamp}.zip"
        zip_path = os.path.join(LOCAL_PROJECT_ROOT, zip_name)

        send_message(f"dist 文件路径：{zip_path}")
        send_message('开始压缩 dist 文件...')

        # 创建ZIP压缩包
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipdir(dist_path, zipf)

        # 在压缩完成后添加验证
        if not os.path.exists(zip_path):
            raise Exception(f"ZIP文件创建失败: {zip_path}")

        send_message(f"ZIP 文件压缩成功, 路径：{zip_path}, 文件大小: {os.path.getsize(zip_path)/1024:.2f} KB")

        try:
            send_message(f"开始部署到 {server_name}...")
            # SSH 连接
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 认证方式处理
            if config.get('auth_type') == 'password':
                ssh.connect(
                    hostname=config['host'],
                    port=config.get('port', 22),
                    username=config['username'],
                    password=config['password']
                )
            else:  # 默认使用密钥认证
                pkey = paramiko.RSAKey.from_private_key_file(config['key_path'])
                ssh.connect(
                    hostname=config['host'],
                    port=config.get('port', 22),
                    username=config['username'],
                    pkey=pkey
                )

            send_message("SSH 连接成功")

            # 创建部署目录（如果不存在）
            ssh.exec_command(f"mkdir -p {config['deploy_path']}")
            send_message("部署目录创建成功")
            # 创建备份目录（如果不存在）
            ssh.exec_command(f"mkdir -p {config['backup_path']}")
            send_message("备份目录创建成功")

            sftp = ssh.open_sftp()
            remote_zip = f"{config['deploy_path']}/{zip_name}"

            send_message(f"开始上传ZIP文件到 {server_name}...")
            # 上传 ZIP 文件, 并返回上传进度
            sftp.put(zip_path, remote_zip, callback=lambda sent, total: send_message(f"上传进度：{int((sent / total) * 100)}%"))
            send_message(f"ZIP 文件上传成功，路径：{remote_zip}")

            # 服务器端操作命令
            commands = [
                f"cd {config['deploy_path']}",
                f"unzip -qo {zip_name} -d dist_{timestamp}",
                f"mv dist {config['backup_path']}/dist_bak_{timestamp} || true",
                f"rm -rf dist",
                f"mv dist_{timestamp} dist",
                f"rm {zip_name}"
            ]

            # 执行命令并获取输出
            stdin, stdout, stderr = ssh.exec_command(' && '.join(commands))
            for line in stdout:
                send_message(f"[{server_name}] {line.strip()}")

        finally:
            send_message(f"关闭 sftp 连接...")
            sftp.close()
            send_message(f"关闭 SSH 连接...")
            ssh.close()
            send_message(f"删除本地ZIP文件...")
            os.remove(zip_path)

    except Exception as e:
        send_message(f"错误: {str(e)}")
        raise

# 执行完整的流程
def run_full_process(server_name):
    """完整流程：检查环境 + 构建 + 部署"""
    # 判断项目根目录是否存在
    if not os.path.exists(LOCAL_PROJECT_ROOT):
        send_message("项目根目录不存在！")
        return

    # 当前工作目录
    send_message(f"当前工作目录：{os.getcwd()}")

    try:
        # 检查Node环境
        send_message("检查Node版本...")
        execute_command("node -v", LOCAL_PROJECT_ROOT)

        # 构建项目
        send_message("开始构建项目...")
        execute_command("npm run build:prod", LOCAL_PROJECT_ROOT)

        # 部署到服务器
        deploy_to_server(server_name)

        send_message("流程执行完成！")
    except Exception as e:
        send_message(f"流程中断: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html', servers=list(SSH_CONFIGS.keys()))

@socketio.on('start_deploy')
def handle_deploy(data):
    server_name = data.get('server')
    if not server_name:
        send_message("错误：请选择目标服务器")
        return
    threading.Thread(target=run_full_process, args=(server_name,)).start()

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=8199)
