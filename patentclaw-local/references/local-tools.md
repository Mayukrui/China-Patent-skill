# 本地预检与合同验证

local_guard.py仅使用Python标准库，不导入PatentClaw、不调用模型、HTTP、shell或TeX，不解析PDF/DOCX内容、不生成实稿、不解压ZIP、不改变网络或系统配置。没有网络API的代码不等于系统无网络，本地执行环境仍需独立核验。

## 命令

先由本地执行者依据contracts.md建立并核验case/privacy_contract.json；门槛未通过时preflight不读论文。批准源目录不含无关材料。

    python scripts/local_guard.py preflight --source <批准源文件或目录> --case <本地case根>
    python scripts/local_guard.py validate --case <本地case根>

输出只有固定结果代码和错误数，不打印路径、hash、原文、异常或证据。详细结果仅写case/local_guard_report.json；来源清单只写case/source_manifest.json。保护这两个文件，禁止自动回传工具输出或日志。

preflight默认：最多2000文件/ZIP成员、总字节150MiB、单文件50MiB、ZIP压缩比200、LaTeX引用深度32、重复展开最多300000字符。它拒绝目录/文件链接和Windows reparse points、外来绝对/驱动/UNC/ADS路径、ZIP穿越/加密/重复成员/非普通文件、跨根或缺失input/include/graphics/bib引用、含危险TeX执行命令或难以静态判定的动态引用。预算是本技能保守限额，不是法律标准。

仅支持有限静态LaTeX语法；不支持的引用应整理隔离源包或人工核验并更新预检，不绕过失败直接喂给原parser。不执行论文中的任何代码；是否纳入源码由批准清单决定。预检只代表当时快照，实际读取前需核对hash，不能用预检抵御并发文件替换。

validate核验privacy、重新核对冻结源文件hash、证据唯一及引用存在性、权利要求支持状态/定位/依赖链、30项和APP表完整性、ready门槛及交付文件类型/根约束。它不验证证据内容蕴含、权利要求真正支持性、Office Math质量、图件语义或法律充分性；这些必须由本地独审完成。

常见危险命令扫描还覆盖.sty/.cls/.bst文本并保守拒绝csname/catcode/scantokens；这可能拒绝合法复杂源包，也不是任意TeX宏执行安全证明。严格禁止执行TeX/宏/样式和源代码；可在本地人工整理不需要这些文件的隔离文本源包，保留原文件及转换来源，不声称转换已覆盖全部语义。

## 不直接执行的项目入口

禁用latex2disclosure-api、patent-reviewer-api、--online、ModelGateway.structured、build_client、web/tools/build_example_data.py与保密材料的Git发布。原CLI读取.env，不能作为保密任务安全默认入口。离线样例也仅结构验证，不替代本地语义写作。

使用已审计、已安装的上游本地解析或规则工具时，显式构造配置并核验有效值，不能依赖默认值、省略在线标志或默认get_settings加载.env：

```python
# Generator Settings；approved_case_root为当前任务已批准的本地工作目录。
Settings(L2D_OFFLINE_MODE=True, OPENAI_API_KEY=None,
         OPENAI_BASE_URL=None,
         L2D_DATA_DIR=approved_case_root / "disclosure", _env_file=None)

# Reviewer Settings；两个Settings分别从对应包导入。
Settings(enable_semantic_review=False, openai_api_key=None,
         output_root=approved_case_root / "review", _env_file=None)
```

这些配置只限制对应程序，不证明操作系统隔离；原生offline不能作为真实语义写作或效果验证。

标准skill验证可在公开配置研究阶段运行：

    python <skill-creator目录>/scripts/quick_validate.py <本技能目录>
    python -m unittest discover -s <本技能目录>/scripts -p "test_*.py"

测试用临时合成材料，不安装新依赖、不调用模型、不使用GPU。

## 专业绘图工具

在获取或安装绘图软件前先查找现有Visio、draw.io等工具并验证可用性。缺工具时从官方发布渠道获取可离线使用的桌面版，遵守安装权限；软件下载请求不包含材料。保存原生可编辑对象与源文件，导出后复核；本预检脚本不代替图件和文档的视觉审查。
