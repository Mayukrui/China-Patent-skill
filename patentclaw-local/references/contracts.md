# 证据、隐私与产物合同

## 隐私合同

接触论文前，在批准本地case根保存privacy_contract.json：

    {
      "schema_version": "patentclaw-local/privacy-1",
      "upload_prohibited": true,
      "content_execution": "manual",
      "egress_control_verified": false,
      "egress_control_record": "",
      "telemetry_and_sync_checked": false,
      "source_and_output_local_verified": false,
      "cloud_content_processing": false
    }

content_execution仅manual或verified_local_model。上例是**未通过模板**。隔离记录由本地执行者核验填入，不能因为用户说禁止上传、有本地文件或脚本通过就代填true。核验覆盖解析/OCR/渲染/模型/子进程的出站通信，本地模型不得有远程fallback。工具不自动改变系统配置。

公开代码研究不需要论文隐私合同。云端助手不接收原文、摘录、截图、派生摘要、公开前技术特征、秘密名称或日志。换执行环境或隔离失效后重新核验；严禁把审计声明当作网络隔离证据。

## 源文件和证据

- source_manifest.json：schema_version为patentclaw-local/source-1，source_root为批准源文件/目录/ZIP本地路径，files保存相对路径path、字节数bytes、SHA-256 sha256；另可记录类型和来源版本。只保存本地，不纳入父目录其他稿、数据、Key或.env；实际读取与终审需核对当前hash。
- evidence.json：数组，每项含evidence_id/source_file/locator/kind/text；kind为text/equation/table/algorithm/figure/code。ID唯一且冻结；保留精确原文和原始文件/页码/段落位置。
- 保留原项目E0001…编号。其section/chunk定位经过合并与截断，不能冒充原始子文件位置；补充original locator。
- feature_ledger.json：数组，含feature_id/description/support/evidence_ids/derivation/essential/status。support为explicit/inherent/needs_confirmation/unsupported；inherent是逻辑上唯一必然推导，不能仅凭合理猜测。status为supported或blocked；未确认核心项为blocked。
- terminology.json：统一术语/缩写、公式符号、张量接口、模块及来源，不新增无来源部件。
- claim_support.json：每条claim_id/topic/depends_on/features。features中每项含feature_id/support/evidence_ids/specification_locators；inherent还含derivation。每一个技术特征都需映射，不用一个整章ID覆盖全部内容。

数字、单位、样本量、数据划分、实验条件、范围和对照分别映射。helper只核验引用和状态，不判断证据蕴含事实。

## 写作范围合同

开始生成前记录用户选择的文件数量、种类、合并方式；推荐四份但不重复确认已有选择。介绍材料不携带具体训练超参数，原始参数只在本地保密证据中保留。默认不引用消融数据；必要数据采用理由、来源与范围留在本地记录。效果图缺源时保存待补状态并询问用户，不能伪造。

## 原项目与扩展产物

原生PipelineJob的paper/evidence/understanding/invention/solution/evidence_package/disclosure/review保持原schema。完整申请、支持状态、APP检查使用本地sidecar JSON关联job ID/hash，不塞入原schema。

TechnicalDisclosure顶层字段：

    invention_title, technical_field, background, prior_art_defects,
    technical_problem, overall_solution, detailed_steps, key_innovations,
    beneficial_effects, embodiments, experimental_evidence, drawing_descriptions,
    terminology, system_implementation, data_and_interfaces,
    implementation_boundaries, alternatives, inventor_confirmation_items

只接收可信本任务job；全部image_path/mermaid_path必须在批准资产根内，拒绝复制其他目录文件。原材料和旧稿保持只读，不删除历史记录。

推荐目录：

    case-root/
      说明.txt
      privacy_contract.json
      source_manifest.json
      evidence.json
      feature_ledger.json
      terminology.json
      claim_support.json
      disclosure/job.json
      disclosure/technical_disclosure.md 与 .docx
      application/权利要求书.md 与 .docx
      application/说明书.md 与 .docx
      application/说明书摘要.md 与 .docx
      application/附图/
      review/initial_review.json
      review/final_review.json
      review/application_checks.json
      review/revision_attempts.json
      review/change_log.json
      review/missing_materials.md
      delivery_status.json

重要生成子目录也有说明.txt，说明用途、来源、保密性与复现。目录须本地且无自动同步，不单凭盘符断言安全；不提交Git、不生成网页示例。

## 检查与修订合同

final_review.json含checklist数组，恰好30个固定ID。每项含check_id/status/reason/evidence_ids/assessed_by。status：pass/fail/needs_human_review/not_applicable/not_assessed。assessed_by：rule_engine/manual/verified_local_model/none。12项语义不能由rule_engine判pass；not_applicable需真实理由，not_assessed不算通过。

application_checks.json含checks数组，恰好APP-01…APP-08，采用相同状态/理由/证据/执行者字段。

finding：finding_id/check_id/target_path/original_text/issue/evidence_ids/requires_inventor_confirmation。

patch：check_id/finding_ids/allowed_target_paths/base_disclosure_hash/target_path/original_fragment/replacement_fragment/evidence_ids/reason。

只替换所在字段恰好出现一次的原片段，引用本issue的finding。证据需存在且实际支持新事实，不删除核心方案，不抹除已知缺口。记录before/after/源版本/应用结果；合并后全表复审。申请稿字段使用APP补丁，不能冒充原项目DisclosureField。

默认3轮，终止原因：all_checks_resolved/no_safe_changes/max_rounds_reached/privacy_blocked/source_incomplete。

## 交付状态

delivery_status.json：

    {
      "status": "incomplete_draft",
      "termination_reason": "source_incomplete",
      "unresolved_core_gaps": ["需要补充的核心事实"],
      "semantic_review_complete": false,
      "export_consistency_checked": false,
      "documents": {}
    }

status仅incomplete_draft/ready_for_inventor_review。ready要求隐私门槛、完整30项与APP检查（适用项全通过）、所有正式权利要求特征有支持、无核心缺口、导出一致。

ready的documents至少claims/specification/abstract/figures/disclosure，每项为case内存在且非链接的相对路径。存在性不是内容检查；仍需章节清晰的MD、匹配DOCX和追溯JSON。实际可实施性和法律充分性需专业人员复核。

工作记录、保护材料与公开skill仓库必须分开。ready中的disclosure为内部追溯产物，不计入四份推荐交付；专业源图可按用户要求另附。不得把用户case的privacy_contract、source_manifest或具体审查报告纳入公开skill。
