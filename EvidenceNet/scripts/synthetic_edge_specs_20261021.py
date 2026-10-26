"""Authored, fictional adversarial text pairs. Labels are NOT model inputs."""


def case(number, family, group, a, b, expected, reason, **extra):
    return dict(id=f"S{number:03d}", family=family, group=group, a=a, b=b,
                expected=expected, reason=reason, **extra)


TREE = "MIRTA (Mountain Inventory of Rare Tree Assemblages) contains 8,400 tree-survey records from alpine forests."
TABLE = "Table 2 of the Pavo acoustic-array study lists its three deployment sites: Alder Pier, Birch Inlet, and Cedar Bay."
CITATION = 'In this article, reference [7] is Venn et al., “Luma Harbour Census” (2041), which counts fishing vessels.'
COMPONENT = "RavoNet uses the VEK-3 compressor to encode vibration measurements before turbine fault prediction."
METRIC = "Root mean squared error (RMSE) is the square root of the arithmetic mean of squared prediction residuals."
DETECTOR = "The VELTA-8 detector estimates a threshold from 228 calibration measurements."
WRAP_A = "For the activation ELU, negative inputs have output alpha times (exp(x) minus one); positive inputs pass through unchanged."
WRAP_B = "ELU returns x when x is positive and alpha multiplied by (exp(x) minus one) when x is negative."
NEG_A = "During experiment ORBIT-4, the NEXA valve did not reduce chamber pressure. Its temperature sensor was replaced after the experiment."
NEG_B = "During experiment ORBIT-4, the NEXA valve reduced chamber pressure. Its temperature sensor was replaced after the experiment."
LONG_A = (
    "The RavoNet field deployment concerns turbine bearings on a coastal wind farm. "
    "Technicians check the mounting bolts before connecting accelerometers to the recording unit. "
    "The enclosure protects the recorder from salt spray, while a separate battery powers the clock. "
    "Maintenance notes distinguish planned shutdowns from unplanned mechanical interruptions. "
    "A red lamp on the enclosure indicates that the local storage medium is almost full. "
    "The service boat carries replacement cables, spare bolts, and a printed inspection checklist. "
    "Each inspection ends with a manual check of the enclosure seal and the power connector. "
    "For compact storage, RavoNet applies the VEK-3 compressor to its vibration measurements. "
    "The compressor stores differences between consecutive samples rather than their absolute values. "
    "This paragraph does not describe the architecture of the downstream fault predictor."
)
LONG_B = (
    "The CerinNet clinical workflow concerns retinal scans collected in an outpatient room. "
    "The operator adjusts the chin rest and asks the participant to look at a fixed marker. "
    "Room lighting remains constant while the instrument captures the retinal image. "
    "A separate form records whether the participant wears corrective lenses. "
    "The clinician reviews the image for motion artifacts before starting lesion segmentation. "
    "Files are archived after the participant leaves, and an administrator checks that the consent form is present. "
    "The monitor is cleaned between appointments and the room is locked at the end of the day. "
)

SPECS = [
    case(1, "identity_collision", "name_minimal_pair", TREE,
         "MIRTA (Microwave Interferometer for Real-Time Alignment) reports antenna phase offsets during receiver calibration.",
         "NO_LINK", "缩写相同，但全名、实体类别与用途不同，不能只匹配 MIRTA 字符串。"),
    case(2, "identity_collision", "name_minimal_pair", TREE,
         "The Mountain Inventory of Rare Tree Assemblages, abbreviated MIRTA, includes tree surveys collected between 2038 and 2040.",
         "RELATED", "明确同一完整名称的数据集，两个端点补充不同属性。"),
    case(3, "local_pointer", "table_minimal_pair", TABLE,
         "Table 2 of the Neris battery-ageing study lists electrolyte formulations and their charge-retention measurements.",
         "NO_LINK", "Table 2 是两篇不同研究的局部编号；不是同一张表。"),
    case(4, "local_pointer", "table_minimal_pair", TABLE,
         "We reproduce the deployment-site list from Table 2 of the Pavo acoustic-array study: Alder Pier, Birch Inlet, and Cedar Bay.",
         "RELATED", "来源、编号和内容均显式匹配，允许跨文档指向同一对象。"),
    case(5, "reference_identity", "citation_minimal_pair", CITATION,
         'In this article, reference [7] is Orel et al., “Navo Battery Ageing” (2043), which studies electrolyte degradation.',
         "NO_LINK", "不同文章的 [7] 不是全局标识，作者、标题和年份均不同。",
         notes="只测语义 verifier，不测或改动独立的 CITES/reference builder。"),
    case(6, "reference_identity", "citation_minimal_pair", CITATION,
         'Our reference [12], Venn et al., “Luma Harbour Census” (2041), provides the vessel census for Luma Harbour.',
         "RELATED", "引用编号不同，但作者、标题和年份明确相同。",
         notes="语义关系诊断，不代表 reference 管线测试。"),
    case(7, "component_scope", "component_minimal_pair", COMPONENT,
         "CerinNet uses the VEK-3 compressor to encode retinal scans before lesion segmentation.",
         "RELATED", "不同父模型和应用保留同一显式组件的关联；不能推断父模型或任务相同。"),
    case(8, "component_scope", "component_minimal_pair", COMPONENT,
         "CerinNet uses the LUM-2 parser to extract dates from invoices before tax auditing.",
         "NO_LINK", "句式相似，但组件、操作、对象和任务均不同。"),
    case(9, "negation", "event_polarity",
         "In trial LANTERN-6, closing valve V4 prevented a pressure surge.",
         "In trial LANTERN-6, closing valve V4 did not prevent a pressure surge.",
         "RELATED", "同一明确事件和操作的相反结论依然相关，但不互相支持。", polarity_conflict=True),
    case(10, "numeric_collision", "number_collision",
         "The Neral Harbour inventory contains 228 fishing-vessel records.",
         "The Tavin chemical atlas reports a boiling temperature of 228 degrees Celsius for compound ZQ-5.",
         "NO_LINK", "同一个数字对应不同实体、属性和单位，不构成 bounded claim 对应。"),
    case(11, "operation_identity", "renamed_projection",
         "In the first formulation, K = XW multiplies an n-by-d input feature matrix X by a learned d-by-r matrix W to produce an n-by-r linear projection K.",
         "In the second formulation, Z = HV multiplies an m-by-p input feature matrix H by a learned p-by-q matrix V to produce an m-by-q linear projection Z.",
         "RELATED", "符号与尺寸命名不同，显式定义的可学习矩阵线性投影操作相同。", notes="数学内容以文字输入，不含公式截图。"),
    case(12, "symbol_collision", "symbol_W",
         "In LaroNet, W denotes a learned weight matrix mapping input features into a latent vector.",
         "In the Dorel soil survey, W denotes the measured water content, expressed as kilograms of water per kilogram of dry soil.",
         "NO_LINK", "变量 W 相同，但一个是模型权重矩阵，另一个是土壤含水量。"),
    case(13, "metric_identity", "metric_minimal_pair", METRIC,
         "Mean absolute percentage error (MAPE) is the arithmetic mean of absolute prediction residuals divided by the corresponding absolute observed values, multiplied by 100.",
         "NO_LINK", "都是误差指标不是同一个定义；无显式比较，只共享用途不足以建立具体关系。"),
    case(14, "metric_identity", "metric_minimal_pair", METRIC,
         "To calculate root mean squared error, square each prediction residual, average these squared values, and take the square root of that average.",
         "RELATED", "同一指标及计算定义的改写，不要求逐字重合。"),
    case(15, "population_scope", "population_minimal_pair",
         "CORIN contains hourly salinity measurements from all 12 stations in the Pelan estuary during 2042.",
         "We use the explicitly identified CORIN subset comprising stations C1, C2, and C3 during January 2042.",
         "RELATED", "明确同一数据集的子集关系；不能当作同样测量总体和时间段。", notes="RELATED 不授权跨总体数值比较。"),
    case(16, "population_scope", "population_minimal_pair",
         "CORIN contains hourly salinity measurements from all 12 stations in the Pelan estuary during 2042.",
         "DARIN contains hourly nitrate measurements from all 12 stations in the Vesko aquifer during 2044.",
         "NO_LINK", "12 个站点和采样频率相同，但数据集、属性、地点与时间不同。"),
    case(17, "unresolved_identity", "pronoun_minimal_pair", DETECTOR,
         "This detector estimates a threshold from 228 calibration measurements.",
         "U", "跨文档的 this detector 没有可解析指代；不能靠相同数量确定身份，也不强标无关。"),
    case(18, "unresolved_identity", "pronoun_minimal_pair", DETECTOR,
         "The VELTA-8 detector estimates a threshold from 228 calibration measurements.",
         "RELATED", "补齐明确名字后，同一对象与同一 bounded claim 均可识别。"),
    case(19, "numeric_collision", "percentage_units",
         "The FENO classifier achieves 95 percent accuracy on the TRAVA handwriting test.",
         "The BERO catalyst achieves a 95 percent chemical yield in the synthesis of compound PQ-2.",
         "NO_LINK", "95% 的数字形式相同，但分别是分类准确率与化学产率。"),
    case(20, "unit_conversion", "temperature_units",
         "During calibration run LORIS-2, chamber Q had a temperature of 300 kelvin.",
         "During calibration run LORIS-2, chamber Q had a temperature of 26.85 degrees Celsius.",
         "RELATED", "同一命名运行和腔体，同一温度仅单位不同。"),
    case(21, "component_scope", "loss_across_tasks",
         "AveroNet trains its depth estimator using the Smooth L1 loss on predicted depths.",
         "BeralNet trains its object detector using the Smooth L1 loss on bounding-box coordinates.",
         "RELATED", "同一显式命名损失函数用于不同任务，保留组件关系而非父模型等同。"),
    case(22, "component_scope", "training_purpose",
         "NavoNet uses the Adam optimizer to update its trainable parameters.",
         "TeriNet uses dropout to randomly zero hidden activations during training.",
         "NO_LINK", "都属于训练过程，但优化器与随机屏蔽机制不是同一具体组件或论断。"),
    case(23, "word_sense", "attention_homonym",
         "The DARTA network computes scaled dot-product attention between query and key vectors.",
         "In the Mevlo museum study, visitors paid attention to the bright red entrance sign.",
         "NO_LINK", "attention 分别是数学机制与日常意义，词面重合不能建立身份。"),
    case(24, "generic_claim", "reduce_template",
         "The Neron pump reduces pressure in the sealed mixing chamber.",
         "The Velcino survey reduces sampling variance by increasing the number of interviewed households.",
         "NO_LINK", "reduce 的谓词形式相同，但作用对象、属性和机制不对应。"),
    case(25, "long_distractors", "distractor_minimal_pair", LONG_A,
         LONG_B + "For compact storage, CerinNet uses the VEK-3 compressor. It stores differences between consecutive samples rather than their absolute values.",
         "RELATED", "多数内容不同，但末尾明确共享 VEK-3 组件及差分存储操作；不能只看段落主主题。"),
    case(26, "long_distractors", "distractor_minimal_pair", LONG_A,
         LONG_B + "For archiving, CerinNet stores each scan as an uncompressed file, sorted by appointment date.",
         "NO_LINK", "移除末尾共享组件后，涡轮维护与视网膜检查只剩泛化工作流程相似。"),
    case(27, "line_break", "wrap_invariance", WRAP_A,
         "ELU returns x when x is positive and alpha multiplied by\r\n(exp(x) minus one) when x is negative.",
         "RELATED", "CRLF 只是同一句的物理折行，不应改变激活函数定义。", invariant_with="S028"),
    case(28, "line_break", "wrap_invariance", WRAP_A, WRAP_B,
         "RELATED", "S027 的去折行对照，语义相同。", invariant_with="S027"),
    case(29, "negation", "negation_wrap_invariance", NEG_A, NEG_B,
         "RELATED", "同一运行与阀门，pressure 结论相反但仍相关；共同的传感器句子不能抹掉冲突。",
         polarity_conflict=True, invariant_with="S030"),
    case(30, "negation", "negation_wrap_invariance",
         "During experiment ORBIT-4, the NEXA valve did\nnot reduce chamber pressure.\n\nIts temperature sensor was replaced after the experiment.", NEG_B,
         "RELATED", "在 did/not 之间折行不应丢掉否定，也不应改变 S029 的相关性。",
         polarity_conflict=True, invariant_with="S029"),
    case(31, "unresolved_identity", "missing_dataset_name",
         "The OSTRA benchmark contains 883 road sensors sampled every five minutes in 2041.",
         "The dataset contains 883 road sensors sampled every five minutes in 2041.",
         "U", "数字和采样属性吻合不等于数据集身份已确定；匿名端点需要额外来源证据。"),
    case(32, "local_pointer", "equation_number_collision",
         "Equation (3) in the JORA report defines the arithmetic mean of measured wave heights.",
         "Equation (3) in the SELKO report defines the rate of radioactive decay as a function of elapsed time.",
         "NO_LINK", "Equation (3) 是文档局部编号；物理量、运算和报告均不同。"),
]
