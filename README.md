# 使用 Python 自动部署 Vue 项目

本仓库包含一个 Python 应用程序，用于自动化部署 Vue.js 项目。它使用 Flask 作为 Web 框架，并通过 SSH 集成远程服务器部署功能。

## 特性

- 自动化部署 Vue.js 应用程序的流程。
- 使用 Flask 创建轻量级的 Web 界面以管理部署。
- 通过 Paramiko 进行 SSH 连接，在远程服务器上执行命令。

## 运行环境

- Python 3.12.6
- Flask
- Paramiko
- Flask-SocketIO

## 安装

要开始使用，请克隆此仓库并安装所需的包：

```bash
git clone https://github.com/yourusername/vue-auto-deploy-python.git
cd vue-auto-deploy-python
pip install flask paramiko Flask-SocketIO
```

需要将项目中的 `config.yaml.bak` 改为 `config.yaml` 并填写里面的相关配置信息

## 运行 Flask 应用程序
```bash
python app.py
```

接下来访问 `http://localhost:8199` 查看 web 界面。
