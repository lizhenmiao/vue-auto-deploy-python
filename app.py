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
      # socketio.emit('command_output', {'data': f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"})
      socketio.emit('command_output', {'data': message})

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
            # send_message(output.strip())
            send_message(output)

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
                # send_message(f"[{server_name}] {line.strip()}")
                send_message(f"[{server_name}] {line}")

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
def run_full_process(server_name, has_remote_origin, branch):
    """完整流程：检查环境 + 构建 + 部署"""
    send_message('🚦 开始部署流程...')

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

        # 判断 branch 是否存在
        if branch:
            send_message(f"切换到分支：{branch}")
            execute_command(f"git checkout {branch}", LOCAL_PROJECT_ROOT)
            # 判断 hasRemoteOrigin 是否存在
            if has_remote_origin:
                send_message("远程仓库存在，尝试拉取最新代码...")
                execute_command("git pull", LOCAL_PROJECT_ROOT)

        # 构建项目
        send_message("开始构建项目...")
        execute_command("npm run build", LOCAL_PROJECT_ROOT)

        # 部署到服务器
        deploy_to_server(server_name)

        send_message("流程执行完成！")
    except Exception as e:
        send_message(f"流程中断: {str(e)}")

# 使用 git 命令判断是不是 git 仓库
def is_git_repo(path):
    try:
        subprocess.check_call(['git', 'rev-parse', '--is-inside-work-tree'], cwd=path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

# 使用 os 命令判断是不是 git 仓库
def is_git_repo2(path):
    return os.path.exists(os.path.join(path, '.git'))

# 判断有没有远程分支
def has_remote_origin(path):
    try:
        subprocess.check_call(['git', 'remote', 'get-url', 'origin'], cwd=path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

# 获取当前分支
def get_current_branch(path):
    try:
        return subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=path, text=True).strip()
    except subprocess.CalledProcessError:
        return None

# 获取远程分支列表
def get_remote_branches(path):
    try:
        # return [branch.strip().replace('origin/', '') for branch in subprocess.check_output(['git', 'branch', '-r'], cwd=path, text=True).strip().split('\n')[1:]]
        return list(map(lambda branch: branch.strip().replace('origin/', ''), subprocess.check_output(['git', 'branch', '-r'], cwd=path, text=True).strip().split('\n')[1:]))
    except subprocess.CalledProcessError:
        return []

# 获取本地分支列表
def get_local_branches(path):
    try:
        return subprocess.check_output(['git', 'branch'], cwd=path, text=True).strip().split('\n')[1:]
    except subprocess.CalledProcessError:
        return []

@app.route('/')
def index():
    # 判断指定目录是否是 git 仓库
    if is_git_repo2(LOCAL_PROJECT_ROOT):
        # 是 git 仓库的话, 获取当前选择的分支名称
        current_branch = get_current_branch(LOCAL_PROJECT_ROOT)

        # 判断有没有远程仓库
        has_remote = has_remote_origin(LOCAL_PROJECT_ROOT)
        if has_remote:
            # 如果有远程仓库, 获取远程分支列表
            remote_branches = get_remote_branches(LOCAL_PROJECT_ROOT)
            # 本地分支列表
            local_branches = []
        else:
            # 如果没有远程仓库, 获取本地分支列表
            remote_branches = []
            local_branches = get_local_branches(LOCAL_PROJECT_ROOT)
    else:
        # 如果不是 git 仓库, 就返回当前本地分支列表与当前选择的分支
        current_branch = None
        remote_branches = []
        local_branches = []

    return render_template('index.html', servers=list(SSH_CONFIGS.keys()), has_remote_origin="true" if has_remote else "false", current_branch=current_branch, remote_branches=remote_branches, local_branches=local_branches)

@socketio.on('start_deploy')
def handle_deploy(data):
    server_name = data.get('server')
    if not server_name:
        send_message("错误：请选择目标服务器")
        return
    has_remote_origin = data.get('hasRemoteOrigin', False)
    branch = data.get('branch', None)
    threading.Thread(target=run_full_process, args=(server_name, has_remote_origin, branch)).start()

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=8199)
