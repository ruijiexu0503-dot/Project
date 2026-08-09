from __future__ import annotations

import argparse, json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl
from .segmentation_ground_truth import evaluate


# Independently annotated from the original aligned page JSON and contents
# pages. Orders identify the first retained Evidence node belonging to an item.
REFERENCE = {
"CERNCourier2022NovDec-digitaledition": [
(1,"Welcome","front_matter"),(6,"Cover","front_matter"),(11,"CAEN waveform digitizers","commercial"),(18,"Contents","front_matter"),
(45,"Wiener/ISEG power supplies","commercial"),(58,"From the editor","editorial"),(79,"Pfeiffer turbopumps","commercial"),
(91,"HL-LHC civil engineering","article"),(103,"FCC-ee designers","article"),(116,"Sustainable mining","article"),(121,"Swiss physics impact","article"),(130,"Quantum Nobel","article"),(138,"CERN open knowledge","article"),(145,"Milky Way history","article"),(148,"UV surprise","article"),(150,"Farewell Microcosm","article"),
(155,"Vacuum navigation advertisement","commercial"),(166,"Testing QED","brief"),(167,"Solar axions","brief"),(173,"QCD gets hotter","brief"),(176,"FCC-ee footprint","brief"),(177,"Swing timing","brief"),(178,"ScandInova pulsed power","commercial"),
(186,"Probing QCD beyond LHC","article"),(199,"Rare B-meson decay","article"),(207,"Hypertriton","article"),(219,"Four-muon kaon decay","article"),(229,"Coriolis flow meter","commercial"),
(240,"JENAS 2022","article"),(249,"Identifying dark matter","article"),(252,"Veneziano at 80","article"),(265,"Catching neutrinos","article"),(279,"IUPAP centennial","article"),(290,"Snowmass 2021","article"),
(318,"Power Innovation advertisement","commercial"),(321,"TeamBest cyclotrons","commercial"),(352,"Neutrinos out of the blue","article"),(388,"IPT UHV feedthroughs","commercial"),(389,"Active Technologies","commercial"),(394,"Crystal collimation","article"),(415,"Supercon wire","commercial"),(421,"Scionix detectors","commercial"),(436,"RadiaSoft/Sirepo","commercial"),(444,"IPPOG outreach","article"),(466,"Mileon conductor","commercial"),(468,"Clean-critical fasteners","commercial"),(479,"Quantum gravity viewpoint","article"),(490,"Evac CeFiX","commercial"),(507,"Fermilab interview","article"),(532,"Deep Learning review","review"),(542,"Infinity of Worlds review","review"),(559,"Plasma accelerators career","article"),
(570,"Breakthrough prizes","brief"),(571,"Dirac medallists","brief"),(574,"Falling Walls prize","brief"),(576,"Lise Meitner prize","brief"),(578,"Odderon recognition","brief"),(580,"Best theses in Spain","brief"),(582,"Alumni Network award","brief"),
(585,"CERN recruitment","commercial"),(589,"ELI Beamlines recruitment","commercial"),(605,"Physics World careers","commercial"),(610,"Harald Fritzsch obituary","obituary"),(621,"Alain Magnon obituary","obituary"),(630,"Karl von Meyenn obituary","obituary"),(635,"François Piuz obituary","obituary"),(648,"R&K RF amplifier","commercial"),
(651,"DESY ant","brief"),(652,"Quantum Kate","brief"),(653,"Media corner","brief"),(659,"From the archive","brief"),(663,"Compiler note","brief"),(664,"Correction","brief"),(665,"Fujikura superconductor","commercial"),(673,"CAEN Sci-Compiler","commercial")],
"CERNCourier2026MayJun-digitaledition": [
(1,"Welcome","front_matter"),(8,"Cover","front_matter"),(12,"ICHEP conference advertisement","commercial"),(23,"Contents","front_matter"),(41,"ICHEP sponsor advertisement","commercial"),(50,"From the editor","editorial"),(94,"IBIC conference advertisement","commercial"),
(109,"Antimatter transport","article"),(122,"Top-antitop excess","article"),(132,"Breakthrough Prize","article"),(146,"NA62 kaon result","article"),(160,"Farewell RHIC","article"),(172,"Galactic pulsars","article"),
(190,"Chile associate member","brief"),(191,"Doubly charmed baryon","brief"),(192,"Timepix chips to Moon","brief"),(195,"SuperKEKB record","brief"),(198,"DESI survey","brief"),(199,"LHC inspection robot","brief"),(200,"Southern-sky neutrinos","brief"),
(206,"Rare Bs decay","article"),(216,"Nuclear coalescence","article"),(226,"Higgs CP tests","article"),(242,"CP violation update","article"),(253,"COMSOL simulation advertisement","commercial"),
(271,"Moriond at 60","article"),(284,"Chamonix workshop","article"),(301,"Dark matter Abu Dhabi","article"),(315,"FCC physics workshop","article"),(333,"Big Science summit","article"),(345,"NIM HV modules","commercial"),(353,"Neutrinos on the clock","article"),(377,"Magnetics advertisement","commercial"),(392,"Bergoz beam-current transformers","commercial"),(407,"TeamBest expansion","commercial"),(425,"Radiopharmaceutical feature","article"),(465,"Metrolab advertisement","commercial"),(476,"Dark web feature","article"),(518,"Signal generator advertisement","commercial"),(532,"TELMAX advertorial","commercial"),(538,"Busch vacuum advertisement","commercial"),(546,"FCC viewpoint","article"),(557,"Supercon wire","commercial"),(563,"IPT feedthroughs","commercial"),(566,"Fabiola Gianotti interview","article"),(601,"Hiden analytical advertisement","commercial"),(612,"Evac CeFiX","commercial"),(615,"CERN recruitment","commercial"),
(619,"Stochastic Cooling review","review"),(624,"Standard Model review","review"),(639,"Die Urknallmaschine review","review"),(658,"Physics with dad jokes","article"),
(672,"Newbold DUNE appointment","brief"),(673,"Turing award","brief"),(674,"Charpak-Ritz award","brief"),(676,"Heineman prize","brief"),(678,"LHCb spokesperson","brief"),(679,"DUNE excavation award","brief"),(680,"Franklin medal","brief"),
(684,"Mark Rayner obituary","obituary"),(695,"Jan Żylicz obituary","obituary"),(706,"Roger Barlow obituary","obituary"),(721,"Michael Wohlmuther obituary","obituary"),(732,"Rayner plot","brief"),(733,"Media corner","brief"),(741,"From the archive","brief"),(744,"Around the Laboratories","brief"),(746,"Compiler note","brief"),(747,"Big Science Business Forum","commercial"),(755,"CAEN DTL27xx","commercial")]
}


def materialize(doc, nodes):
    by_order={n["document_order"]:n for n in nodes}; rows=[]
    for number,(order,label,kind) in enumerate(REFERENCE[doc],1):
        node=by_order[order];rows.append({"item_number":number,"label":label,"kind":kind,
            "start_document_order":order,"start_node_id":node["node_id"],"source_page":(node.get("page_ids") or [None])[0],
            "start_text":node.get("plain_text","")[:240]})
    return rows


def evaluate_items(reference, nodes, assignments):
    order={n["node_id"]:n["document_order"] for n in nodes}; item={order[r["node_id"]]:r["content_item_id"] for r in assignments}
    starts=[r["start_document_order"] for r in reference]; maximum=max(item); results=[]
    for index,row in enumerate(reference):
        start=row["start_document_order"];end=starts[index+1]-1 if index+1<len(starts) else maximum
        ids={item[value] for value in range(start,end+1)}
        boundary_before=start==1 or item[start]!=item[start-1]
        boundary_after=end==maximum or item[end]!=item[end+1]
        results.append({**row,"end_document_order":end,"boundary_before":boundary_before,
                        "boundary_after":boundary_after,"internal_segment_count":len(ids),
                        "cleanly_separated":boundary_before and boundary_after and len(ids)==1})
    summary={}
    for kind in sorted({r["kind"] for r in results}):
        selected=[r for r in results if r["kind"]==kind]
        summary[kind]={"reference":len(selected),"clean":sum(r["cleanly_separated"] for r in selected)}
    summary["all"]={"reference":len(results),"clean":sum(r["cleanly_separated"] for r in results)}
    return results,summary


def main():
    p=argparse.ArgumentParser();p.add_argument("--doc-id",required=True,choices=sorted(REFERENCE));p.add_argument("--nodes",required=True)
    p.add_argument("--assignments",required=True);p.add_argument("--output-dir",required=True);args=p.parse_args()
    nodes=read_jsonl(args.nodes);reference=materialize(args.doc_id,nodes);assignments=read_jsonl(args.assignments)
    results,summary=evaluate_items(reference,nodes,assignments);out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    order={node["node_id"]:node["document_order"] for node in nodes}
    scored=[{**row,"document_order":order[row["node_id"]]} for row in assignments]
    write_jsonl(out/"ground_truth_items.jsonl",reference);write_jsonl(out/"item_evaluation.jsonl",results)
    report={"doc_id":args.doc_id,"annotation_source":"original aligned pages and contents page","summary":summary,
            "exact":evaluate(reference,scored,0),"tolerance_1":evaluate(reference,scored,1),
            "tolerance_2":evaluate(reference,scored,2)}
    write_json(out/"evaluation.json",report);print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__=="__main__":main()
