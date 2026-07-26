# 芯片数据转换工具

一个面向芯片验证工作的本地数据处理工具，支持 SystemVerilog 数值、逐 bit 映射、逻辑运算、进制转换、bit/byte 反向、字段提取、Actual/Expected 对比、Parity/CRC、代码生成、批量处理和规则模板。

## 启动

双击 `start.bat`，或在 PowerShell 中执行：

```powershell
cd "C:\Users\zhuzh\Documents\AI proj\chip_data_tool"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

浏览器会打开 `http://localhost:8501`。数据仅在本机处理。

当前目录已经包含配置完成的独立 `.venv`。如果以后需要重建环境，可以在本目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果官方 PyPI 在当前网络下连接失败，可以使用：

```powershell
.\.venv\Scripts\python.exe -m pip install `
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple `
  -r requirements.txt
```

## 迁移到另一台电脑

项目源码、配置和用户模板可以直接复制，但不要依赖复制过去的 `.venv`。虚拟环境会记录创建它的电脑上的 Python 绝对路径，即使两台电脑都是 Windows，也可能因为用户名、安装目录或 Python 版本不同而失效。

推荐使用以下迁移步骤：

1. 复制整个 `chip_data_tool` 文件夹到新电脑。为了减小体积，可以在复制前删除 `.venv`；如果已经复制，也请删除新电脑上的旧 `.venv`。
2. 在新电脑安装 64 位 Python 3.12。
3. 在新电脑的 `chip_data_tool` 目录中打开 PowerShell，执行：

```powershell
py -3.12 -m venv .venv

.\.venv\Scripts\python.exe -m pip install `
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple `
  -r requirements.txt
```

4. 安装完成后双击 `start.bat`，或者执行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

浏览器打开 `http://localhost:8501` 后即可使用。用户保存的 JSON 模板位于 `configs` 目录，只要复制了该目录，模板也会一起迁移。

如果新电脑不能访问网络，需要提前下载依赖 wheel，或者制作包含 Python 和依赖的便携发行包。Windows 的 `.venv` 不能直接用于 Linux；Linux 环境需要重新创建对应的虚拟环境。

## 支持的输入

```text
32'h1234_5678
8'shFF
0x1234_5678
0b1010_1100
305419896
12 34 56 78    # 选择“字节流”格式
```

自动模式下，带 `0x` 的数据识别为十六进制，带 `0b` 的数据识别为二进制，包含 A-F 的裸数据识别为十六进制，纯数字识别为十进制。

## 字段映射语法

映射逐行填写，覆盖全部输出 bit：

```systemverilog
output[31:24] = input[7:0]
output[23:20] = input[31:28]
output[19:16] = 4'h0
output[15:0]  = input[27:12]
```

也支持与左侧字段等宽的上下文常量 `'0` 和 `'1`。程序会拒绝越界、重叠、漏赋值和左右宽度不一致的映射。

逐 bit 和表达式映射：

```systemverilog
output[3] = input[0]
output[2] = ~input[1]
output[1] = input[7] ^ input[6]
output[0] = ^input[3:0]
```

二元表达式支持 `^`、`&`、`|`、`+` 和 `-`，两侧字段必须与输出字段等宽。归约表达式支持 `^`、`~^`、`&` 和 `|`，结果为 1 bit。

## 点击编辑输入 bit

“输入 bit 视图”中的每个 bit 都是按钮。点击某个按钮会在 `0` 和 `1` 之间切换，原始输入会同步改写成等宽的 SystemVerilog 十六进制数据，后续流水线、对比结果、Parity/CRC 和代码生成结果也会自动重新计算。

为了避免超宽数据一次创建过多界面控件，位宽不超过 256 bit 时提供点击编辑；更宽的数据仍会显示只读 bit 视图，并正常参与全部运算。

## 运算与分析

- AND、OR、XOR、XNOR、NOT、ADD、SUB。
- 支持整段数据逐 bit 逻辑运算，也支持选择两个指定 bit 做 AND、OR、XOR 或 XNOR，再把结果写入目标 bit。
- 支持按自定义 N bit 分组做 AND、OR、XOR 或 XNOR 归约，每组输出 1 bit；可选择从 LSB 或 MSB 开始输出分组结果。
- 逻辑左/右移、算术右移、循环左/右移。
- 设置、清除或翻转指定 bit。
- 追加奇校验或偶校验 bit。
- Actual/Expected 逐 bit 对比；Expected 中的 `X`、`Z`、`?` 作为 don't-care。
- CRC-8、CRC-16/CCITT-FALSE、CRC-32/ISO-HDLC。
- 将当前流水线生成 SystemVerilog function。

例如对 `32'h1234_5678` 从 LSB 开始每 2 bit 做 XOR 归约：

```systemverilog
output[0]  = ^input[1:0];
output[1]  = ^input[3:2];
// ...
output[15] = ^input[31:30];
```

输出为 `16'h52FA`。输入位宽必须能够被每组位数整除。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

核心逻辑在 `core` 目录中，不依赖 Streamlit，可直接被其他 Python 脚本或回归工具调用。
