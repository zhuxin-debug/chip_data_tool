# 芯片数据转换工具

一个面向芯片验证工作的本地数据处理工具，支持 SystemVerilog 数值、逐 bit 映射、逻辑运算、进制转换、bit/byte 反向、字段提取、Actual/Expected 对比、Parity/CRC、代码生成、批量处理和规则模板。

## 本次完善

- 保留独立 Python 计算核心与 Streamlit 网页界面。
- 可交互位映射：选择流水线步骤，点击输出位，高亮本步输入来源并追溯到原始输入。可下载为无需服务器的独立 HTML 报告。
- 流水线支持编辑、复制、启用/停用、排序、删除，以及最近 40 个工作状态的撤销/重做。
- 输入、结果和对比位视图每页最多 64 bit，支持查看全部范围；宽输入同样可点击编辑。
- 增加补零扩展、符号扩展、低位截断，以及加减进位、借位和补码溢出提示。
- 支持完整工作现场 JSON 导入/导出和本机自动恢复；模板同名覆盖需明确勾选。
- 批处理支持 UTF-8 TXT / 带列名 CSV 导入、失败行筛选、CSV 导出，以及包含处理配置的 JSON 报告。配置改变后旧结果禁止导出，须重新执行。
- CRC 支持明确的字节顺序、实际字节序列预览，以及 8～64 bit 自定义参数。
- 转换失败后，对比与校验不会隐式使用原始输入；用户可以明确选择原始输入或手动输入。
- SV 导出使用经过解析的合法定宽常量，函数名自动规范化，停用步骤与位宽转换也能生成对应代码。

## 建议使用流程

1. 输入数据，按需要指定位宽与符号类型。
2. 添加转换步骤，查看每步中间结果和提示。
3. 在“可交互位映射”选择步骤、点击输出 bit，或输入位号定位。
4. 对比或 CRC 页面明确选择需要分析的数据来源。
5. 常用规则存为模板；需要完整复现时，导出工作现场或批处理结果与配置 JSON。

位映射显示的是**结构依赖**：加减法包含进位/借位链，归约与 Parity 依赖多个输入位；它不是实际 RTL 仿真器或时序波形查看器。

## 启动

双击 `start.bat`，或在 PowerShell 中执行：

```powershell
cd "C:\Users\zhuzh\Documents\AI proj\chip_data_tool"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

通过 `start.bat` 启动时，优先使用 `http://127.0.0.1:8501`；端口被占用则自动尝试 8502～8520。重复启动会打开本项目已运行的实例。保留启动窗口，按 Ctrl+C 停止服务。服务仅监听本机。

首次使用且缺少环境时，`start.bat` 会调用 `setup.bat` 创建环境并安装依赖。需要预装 Python 3.10 或更高版本，推荐本项目使用的 Python 3.12。环境损坏时可单独运行 `setup.bat` 修复；依赖安装需要网络，失败信息会保留在窗口中。

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

输入按每页最多 64 bit 显示；使用“输入位范围”切换高低位页面。宽数据也能点击修改，不会一次创建几千个按钮。完整数据参与所有计算。

## 运算与分析

- AND、OR、XOR、XNOR、NOT、ADD、SUB。
- 支持整段数据逐 bit 逻辑运算，也支持选择两个指定 bit 做 AND、OR、XOR 或 XNOR，再把结果写入目标 bit。
- 支持按自定义 N bit 分组做 AND、OR、XOR 或 XNOR 归约，每组输出 1 bit；可选择从 LSB 或 MSB 开始输出分组结果。
- 逻辑左/右移、算术右移、循环左/右移。
- 设置、清除或翻转指定 bit。
- 追加奇校验或偶校验 bit。
- 补零扩展、符号扩展、保留低位截断。
- Actual/Expected 逐 bit 对比；Expected 中的 `X`、`Z`、`?` 作为 don't-care。
- CRC-8、CRC-16/CCITT-FALSE、CRC-32/ISO-HDLC，以及自定义 8～64 bit 参数。
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

额外的 SystemVerilog 编译与等价检查使用 slang 的 Python 绑定：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

这组检查对生成函数执行 SV 编译和常量求值，覆盖单字节全部 256 个值、多步组合与宽数据，再与 Python 引擎逐项比较。它不替代项目中的时序仿真；未安装开发依赖时该组测试会明确跳过。

## 保存与迁移说明

- 自动保存位于 `.local/workspace.json`，包括输入、规则、批量文本、对比值和校验设置，不写入 Git。
- 同一项目多个浏览器会话共用恢复文件，以最后保存的会话为准；多个独立工作请分别导出 JSON。
- 撤销/重做历史和批处理已计算结果仅在当前会话中保留。恢复现场后重新执行批处理；需要保留结果请下载报告。
- 关闭本会话的自动保存不会删除以前的恢复文件。
- 用户模板位于 `configs`。新电脑需要重建 Python 环境；也可以导入导出的工作现场。交互映射 HTML 可单独双击查看。
- 本次提供本机网页运行方式和安装脚本，尚未打包为内置 Python 的独立 EXE。
