#!/usr/bin/env python3
"""Source-linked weekly case review; reads completed experiments only."""
from __future__ import annotations
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import zipfile
from run_node_context_edges import ROOT, rows, read, write, sha

OUT=ROOT/'EvidenceNet/output/weekly_edge_review_20261023'
OLD=ROOT/'migration/horeka-edge-context-20261020/results'
FRESH=ROOT/'migration/horeka-edge-fresh-20261021/results'
REAL=ROOT/'migration/horeka-edge-real-text-20261022/results'
SYN=ROOT/'migration/horeka-edge-synthetic-20261022/results'
GRAN=ROOT/'migration/horeka-edge-granularity-20261022/results'
LINKS={'EVIDENCE_LINK','NAVIGATION_LINK'}
LABELS={'EVIDENCE_LINK':'E · 证据型提议','NAVIGATION_LINK':'N · 导航型提议','NO_LINK':'X · 不连接','UNCERTAIN':'U · 弃答'}

def load(folder,arm,case,refs='reference.jsonl'):
    reference=next(r for r in rows(folder/refs) if r['suite_case_id']==case)
    tid=reference['task_id']
    entry=next(e for e in rows(folder/arm/'inputs.jsonl') if e['task']['task_id']==tid)
    pred=next((e for e in rows(folder/arm/'predictions.jsonl') if e['task_id']==tid),None)
    return reference,entry,pred

def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'assets').mkdir(exist_ok=True)
    sources={};assets={}
    def source(path):
        sources[str(path.relative_to(ROOT))]=sha(path)
        return os.path.relpath(path,OUT)
    def variant(folder,arm,case,label,refs='reference.jsonl'):
        ref,e,p=load(folder,arm,case,refs)
        src=[source(folder/refs),source(folder/arm/'inputs.jsonl')]
        if (folder/arm/'predictions.jsonl').exists():src.append(source(folder/arm/'predictions.jsonl'))
        result=(p or {}).get('result') or {}
        ends={}
        for side in ('A','B'):
            ids=set()
            endpoint=e['task'][side]
            if endpoint.get('node_source_image_number'):ids.add(endpoint['node_source_image_number'])
            ids.update(v['image_number'] for v in endpoint['evidence'] if v.get('image_number'))
            images=[]
            for number in sorted(ids):
                raw=e['images'][number-1];path=Path(raw)
                if not path.is_file() and '/Project/' in raw:path=ROOT/raw.split('/Project/',1)[1]
                if not path.is_file():images.append({'missing':raw});continue
                digest=sha(path);name=digest[:24]+path.suffix.lower()
                target=OUT/'assets'/name
                if not target.exists():shutil.copy2(path,target)
                assets[name]=digest;images.append({'src':'assets/'+name,'sha256':digest,'number':number})
            ends[side]={'node_id':endpoint['node_id'],'evidence':endpoint['evidence'],'images':images,
                        'anchors':e.get('lookups',{}).get(side,{}),'context':e.get('contexts',{}).get(side,[])}
        return {'label':label,'arm':arm,'case':case,'decision':result.get('decision','MISSING/INVALID'),
                'reason':result.get('reason',''),'result':result,'endpoints':ends,'sources':src,
                'matches':e['task'].get('candidate_matches',[]),'valid':bool(p and p.get('valid'))},ref
    cards=[]
    def add(case,title,category,status,summary,a,b,diagnosis,limit,versions):
        vs=[];ref=None
        for folder,arm,cid,label,rf in versions:
            v,ref=variant(folder,arm,cid,label,rf);vs.append(v)
        cards.append({'id':case,'title':title,'category':category,'status':status,'summary':summary,
            'a':a,'b':b,'diagnosis':diagnosis,'limit':limit,'versions':vs,'reference':ref})
    def mm(folder,cid):return [(folder,'control',cid,'同轮原始输入','reference.jsonl'),(folder,'multimodal_context',cid,'加入来源上下文','reference.jsonl')]
    def txt(cid,synthetic=False):
        folder=SYN if synthetic else REAL
        return [(folder,a,cid,label,'reference.jsonl') for a,label in [('control','整段纯文本'),('text_scope','放宽局部关系范围')]]
    def spans(cid):return [(GRAN/'verifier',arm,cid,label,'reference.jsonl') for arm,label in [('control','96 词匹配＋上下文'),('physical_line','物理逐行＋上下文'),('sentence','完整句＋上下文')]]
    add('P15','EuroSAT：样例图 ↔ 混合数据集表格','跨模态','本周改善',
        '来源上下文帮助模型定位表格中真正的 EuroSAT 行，修复这一次漏连。',
        '图注明确写着 EuroSAT，图中是十类地表样本。','表格列了多个数据集，其中一行也是 EuroSAT。',
        '原始判断误把表格末行 FUSU 当作整体身份；加入指向 Figure 1 的原文后，模型选择了 EuroSAT 行。',
        '这是固定 pair 的核验改善；不等于全量候选召回已解决，也不能把上下文当作新的端点证据。',mm(OLD,'P15'))
    add('F010','PEMS08 / PeMSD8：表格与文字的别名、属性对齐','跨模态','稳定通过',
        '可利用名称、传感器数量和时间范围共同核对同一数据集。',
        '表格：PEMS08，170 个节点，2016 年 7–8 月。','文字：PeMSD8，170 个传感器，2016 年 7–8 月。',
        '名称写法不同，但关键属性一致；两组都正确建立对应。',
        '属于当前稳定通过的 hard case；本轮没有 NO_LINK→RELATED 的新增修复。',mm(FRESH,'F010'))
    add('N22','架构图与分类样本：同领域不等于同一对象','跨模态','稳定通过',
        'FUSU-Net 架构图与 EuroSAT 样本图没有因遥感领域相同而被错连。',
        'FUSU-Net 的双分支架构与融合模块。','EuroSAT 的十类地表样本。',
        '当前 control 和上下文组都拒绝连接。应依据原始命名对象与可比内容，而非视觉相似。',
        '稳定通过案例，不宣称这是本周新增修复；理由里对 Sentinel 与 EuroSAT 的措辞也不应被当成独立事实。',mm(OLD,'N22'))
    add('F028','两张性能表：训练耗时 ≠ 分类准确率','跨模态','稳定通过',
        '识别表格的对象、任务与指标不同，拒绝宽泛的“都是性能表”关联。',
        '交通预测模型每个 epoch 的训练时间。','图像分类模型准确率与预训练准确率。',
        '两组都判不连，避免由同样的表格外形推出语义对应。',
        '这验证负例判断；不是所有表格中的数字关系都已正确解析。',mm(FRESH,'F028'))
    add('F033','MAPE ↔ RMSE：同一用途被误当成同一命题','公式','未解决',
        '两组仍把不同误差指标判成证据型关联，和当前负例标注冲突。',
        'MAPE：绝对误差除以真实值后求平均。','RMSE：平方误差平均后开根号。',
        '模型理由强调“都是预测评价指标”，没有建立具体的同一机制或相同命题。',
        '按当前标注是明确错连；若以后允许“同类指标导航”，需要新定义和重新审查，不能直接改旧分数。',mm(FRESH,'F033'))
    add('F015','Attention 的 Key 投影：上下文反而导致退化','公式','未解决',
        '补上相邻 Q/V 公式后，模型更强调变量和应用差异，关联判断退化。',
        '空间 Attention 中 K = X̂ Wk 的投影。','多头 Attention 中 Ki = X Wik 的投影。',
        'control 给导航关联，补上下文后变成不连；新上下文没有保证模型对齐到共享操作。',
        '当前参考为 E；control 的 N 也不是严格类型正确。不能将其称为原来已完全解决。',mm(FRESH,'F015'))
    add('F006','Land use / land cover：局部定义被逐行方案救回','纯文本','部分改善',
        '逐行核验判断正确，但检索排名仍在预算之外，端到端尚未救回。',
        'Land use 对应人类活动；land cover 对应地表物理材料。','Land use 变化需要理解人类活动；land cover 更直接对应像素值。',
        '逐行的两个焦点将共同定义显式对齐，减少整段讨论主题的干扰。',
        '真实池排名 498，预算前 200，因此这次是“强制送入核验能判对”，不能算检索已解决。',txt('FRESH_F006')+spans('FRESH_F006'))
    add('S021','Smooth L1：共同组件仍被不同任务否决','纯文本','部分改善',
        'scope 组能连上，但滑窗、逐行、完整句版本仍漏掉，改善不稳定。',
        'AveroNet 在深度估计上使用 Smooth L1。','BeralNet 在目标检测框回归上使用 Smooth L1。',
        '两端都有明确的同名损失函数；模型却反复要求相同父模型或任务。',
        '这是人为合成压力样本；有一次救回不代表稳定能力或真实语料准确率。',txt('S021',True)+spans('S021'))
    add('U03','Adam＋交叉熵：共享组件与不同训练设置','纯文本','部分改善',
        '放宽范围能救回，但后续三个片段方案仍漏连。',
        'Adam、交叉熵；最多 150 epochs，patience 15。','Adam、交叉熵；early stopping 为 10 epochs。',
        '共同训练组件不要求整体实验相同；训练设置差异应保留，而不是自动否决所有关联。',
        'OLD_U03 的 U 是历史编号，不是 U 待定标签。本例原标注为宽相关。',txt('OLD_U03')+spans('OLD_U03'))
    add('N03','放宽范围的代价：Adam / RMSprop 不能当同一组件','纯文本','未解决',
        'scope 把不同优化器与损失函数的泛类别当成共同命名组件，引入错连。',
        'Adam 与 categorical cross-entropy。','RMSprop 与 MAE。',
        '扩大关系范围提升部分正例，同时带来负例误连；不能只报告救回的样本。',
        '这是 verifier 输出；现有导出阶段会把缺少已核对 identity 的导航提议送审，不能说已进入正式图。',txt('OLD_N03'))
    add('F020','结构字段与理由矛盾：说不该连，却输出导航','纯文本','未解决',
        'scope 的 reason 与 decision 不一致，结构有效并不代表语义自洽。',
        'GRU / CTVGCRU 的方法描述。','ImageNet 预训练模型描述。',
        '模型理由明确倾向 NO_LINK，但输出 NAVIGATION_LINK；需要单独审计决策一致性。',
        '单纯增加 JSON 校验无法保证语义正确；更严导出规则也会增加正例待审量。',txt('FRESH_F020'))
    add('S030','did\nnot：识别了否定，仍不知道矛盾该怎样连','纯文本','部分改善',
        '逐行方案关联正确；滑窗和完整句识别出否定，却将矛盾视为无关联。',
        'ORBIT-4 实验：NEXA 阀门 did\nnot reduce pressure。','同一实验、同一阀门：reduced pressure。',
        '模型理由已读懂“没有降低”；剩余问题主要是关联与支持的关系定义。',
        '合成例子；关联不表示支持。新语义标签试验的结果尚未在本页核验纳入。',spans('S030'))
    add('S027','ELU 物理换行：稳定通过的文本对照','纯文本','稳定通过',
        '换行本身不一定导致错误：此对照在旧四组中都正确关联。',
        'ELU：负输入使用 α(exp(x)−1)，正输入保持不变。','同一定义的另一种表述，带 CRLF 物理折行。',
        '保留原始换行作为来源；可读视图用于模型输入。不能由此推断所有断句问题已解决。',
        '合成控制样本；只说明这个例子稳定，不代表逐行检索一定优于完整句。',txt('S027',True))
    add('P26','具体 AI 项目 ↔ 通用 AI 定义：标注边界','纯文本','边界待审',
        '旧标签为相关，但当前规则排除泛泛领域关联；失败不能一概解释成读不懂。',
        'UMBRELLA：AI 辅助卒中诊疗。','AI RMF 中 AI 系统的一般定义。',
        '当前多个版本都拒绝连接，在现行严格规则下有合理依据。',
        '保留原标注和分数；应单独复核标签—规则一致性，而不是直接重标提高准确率。',txt('OLD_P26')+spans('OLD_P26'))
    for card in cards:
        preferred={'F006':'physical_line','S021':'text_scope','U03':'text_scope','S030':'physical_line'}
        card['initial_version']=next((i for i,v in enumerate(card['versions']) if v['arm']==preferred.get(card['id'])),max(0,len(card['versions'])-1))
    data={'title':'EvidenceNet · 本周进展与困难案例','period':'2026.10.19 — 10.23','cases':cards,
          'sources':sources,'asset_sha256':assets,
          'notes':['精选、已检查的诊断案例，不是总体准确率或独立测试集。',
                   'E/N/X/U 是历史 verifier 输出；E 也只是模型提议，不是自动可信的证据传播边。',
                   '原始证据、图像、模型理由与来源文件均可展开。绿色表示该例改善或通过，不表示已全面解决。',
                   '不同实验输入与策略有所不同，不把多个版本串成严格的累计增益。',
                   '5207019 新语义标签结果尚未同步核验，本页不编造该试验的改善。']}
    write(OUT/'cases.json',data)
    template=Path(__file__).with_name('weekly_edge_review.html').read_text()
    encoded=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
    (OUT/'index.html').write_text(template.replace('/*__DATA__*/',encoded))
    write(OUT/'manifest.json',{'code':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),Path(__file__).with_name('weekly_edge_review.html')]},
          'sources':sources,'assets':assets,'cases':len(cards),'files':{f:sha(OUT/f) for f in ['cases.json','index.html']}})
    with zipfile.ZipFile(OUT/'weekly_review.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in [OUT/'index.html',OUT/'cases.json',OUT/'manifest.json',*sorted((OUT/'assets').glob('*'))]:z.write(p,p.relative_to(OUT))
    print(json.dumps({'cases':len(cards),'assets':len(assets),'output':str(OUT/'index.html')}))

if __name__=='__main__':main()
