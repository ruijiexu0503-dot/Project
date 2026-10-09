#!/usr/bin/env python3
"""Build an auditable multi-page manifest without changing the original sample."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    original = json.loads((ROOT / 'EvidenceNet/config/sources/relation_first_corpus_sources.json').read_text())
    pdfs = list((ROOT / 'data').rglob('*.pdf'))
    result = []
    corpus = {
        'CERNCourier2022NovDec-digitaledition': 'magazine_corpus_v1/cern_courier_2022_nov_dec',
        'CERNCourier2025JanFeb-digitaledition': 'magazine_corpus_v1/cern_courier_2025_jan_feb',
        'CERNCourier2026MayJun-digitaledition': 'magazine_corpus_v1/cern_courier_2026_may_jun',
        'CLADmag_2025_H2': 'magazine_corpus_v1/cladmag_2025_h2',
        'nist_ai_rmf_1_0': 'government_financial_v1/nist_ai_rmf_1_0',
        'nvidia_2026_annual_report': 'government_financial_v1/nvidia_2026_annual_report',
    }
    for source in original['sources']:
        row = copy.deepcopy(source)
        if row['mode'] == 'pptx':
            for number in (4, 20):
                result.append({**row, 'page': f'slide_{number:04d}', 'slide_number': number,
                               'source_file': row['pptx'], 'page_space': 'native_slide'})
            continue
        if row['mode'] == 'fresh_image':
            result.append({**row, 'source_file': row['image'], 'page_space': 'raster'})
            continue
        pdf = ROOT / row['pdf'] if row.get('pdf') else next(p for p in pdfs if p.stem == row['document_id'])
        row['source_file'] = str(pdf.relative_to(ROOT))
        row['page_space'] = ('source_pdf_page' if row['mode'] in {'fresh', 'corpus'} or row['document_id'] == 'DLRmagazine_176_EN'
                             else 'existing_render_page')
        result.append(row)
        if row['document_id'] == 'nasa_cosmic_temperatures_image_only_pdf':
            continue
        numbers = (12, 17) if row['document_id'] == 'DLRmagazine_176_EN' else (6,)
        for number in numbers:
            page = f'page_{number:04d}'
            extra = {'document_id': row['document_id'], 'page': page, 'page_number': number,
                     'pdf': str(pdf.relative_to(ROOT)), 'source_file': str(pdf.relative_to(ROOT)),
                     'page_space': 'source_pdf_page', 'mode': 'fresh',
                     'case_id': f"relation_{row['document_id']}_{page}"}
            if row['document_id'] in corpus:
                extra.update(mode='corpus', work=f"parsing/experiments/dolphin_v2_pilot/work/{corpus[row['document_id']]}/pages/{page}")
            if row['document_id'] == 'DLRmagazine_176_EN':
                extra.update(mode='case', work=row['work'], image=row['image'])
                extra['native_override_required'] = True
            result.append(extra)
    actual = {r['source_file'] for r in result}
    expected = {str(p.relative_to(ROOT)) for p in (ROOT / 'data').rglob('*') if p.suffix.lower() in {'.pdf', '.jpg', '.jpeg', '.pptx'}}
    assert actual == expected, (expected - actual, actual - expected)
    assert len({(r['document_id'], r['page']) for r in result}) == len(result)
    target = ROOT / 'EvidenceNet/config/sources/relation_first_multisample_sources.json'
    target.write_text(json.dumps({'experiment': 'relation_first_multisample_v3', 'sources': result,
        'selection': 'original regression pages plus source PDF page 6; DLR 9/12/17; slides 4/20; single-page inputs exempt',
        'source_count': len(actual), 'page_count': len(result)}, indent=2) + '\n')
    print(json.dumps({'sources': len(actual), 'pages': len(result), 'manifest': str(target)}))


if __name__ == '__main__':
    main()
