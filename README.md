依据现有轮子修改

增加随机邮箱以及 自定义邮箱

不是很完美,但是满足我自己使用了!

1.创建虚拟环境
```bash
python3 -m venv mail
```
2.进入虚拟环境
```bash
source mail/bin/activate
```
3.安装环境
```bash
pip3 install -i requirements.txt
```
4.运行程序(或直接运行第5步)
```bash
python3 -u main.py -port=9999 -domain=mkfrj.com
```
5.后台运行
```bash
$ nohup python3 -u main.py -port=9999 -domain=mkfrj.com &
```

修改自:https://github.com/rev1si0n/another-tmp-mailbox


