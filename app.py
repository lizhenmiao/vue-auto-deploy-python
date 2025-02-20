from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import subprocess
import os
import threading

app = Flask(__name__)
socketio = SocketIO(app)

# 指定的盘符和目录
drive = "E:"
directory = r"\My_Developments\test-vscode-vue"  # 替换为你的目录路径

def execute_command(command):
    """在当前工作目录下执行给定的命令，并将输出通过 WebSocket 实时发送。"""
    os.chdir(directory)  # 切换到指定目录
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # 逐行读取标准输出
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            socketio.emit('command_output', {'data': output.strip()})

    # 检查标准错误输出
    stderr = process.stderr.read()
    if stderr:
        if "error" in stderr.lower():
            # socketio.emit('command_output', {'data': "错误信息: " + stderr.strip()})
            print("错误信息:", stderr.strip())
        else:
            # socketio.emit('command_output', {'data': "警告信息: " + stderr.strip()})
            print("警告信息:", stderr.strip())

def run_commands():
    """顺序执行多个命令。"""
    commands = ["node -v", "npm run build:prod"]  # 定义要执行的命令列表
    for command in commands:
        socketio.emit('command_output', {'data': "开始执行命令: " + command})
        execute_command(command)  # 依次执行每个命令

@app.route('/')
def index():
    """返回 HTML 页面的入口."""
    return render_template('index.html')

@socketio.on('run_command')
def handle_run_command():
    """处理命令运行请求，顺序执行命令。"""
    threading.Thread(target=run_commands).start()

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=8199)