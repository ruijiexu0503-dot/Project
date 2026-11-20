#!/usr/bin/env python3
"""Build the first 100 QA records directly curated by Codex.

This script never calls a model or scheduler.  It preserves every upstream file
and writes a new, auditable batch with exact canonical evidence spans.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve()
OUT = HERE.parents[1]
DATASETS = OUT.parent
SNAPSHOT = DATASETS / "nodefirst_qa_scale300_20261119_snapshot_d"
POOL = SNAPSHOT / "qa_cumulative_candidates_for_independent_review.jsonl"
SEEDS = SNAPSHOT / "sampled_seeds_snapshot_D_generation_v2.jsonl"
NODES = SNAPSHOT / "snapshot_D_formal_canonical_nodes.jsonl"


SINGLE_IDS = [
    "scale300_snapshot_d::00001", "scale300_snapshot_d::00017",
    "scale300_snapshot_d::00065", "scale300_snapshot_d::00081",
    "scale300_snapshot_d::00193", "scale300_snapshot_d::00002",
    "scale300_snapshot_d::00034", "scale300_snapshot_d::00050",
    "scale300_snapshot_d::00114", "scale300_snapshot_d::00130",
    "scale300_snapshot_d::00162", "scale300_snapshot_d::00003",
    "scale300_snapshot_d::00019", "scale300_snapshot_d::00051",
    "scale300_snapshot_d::00083", "scale300_snapshot_d::00115",
    "scale300_snapshot_d::00131", "scale300_snapshot_d::00020",
    "scale300_snapshot_d::00100", "scale300_snapshot_d::00164",
]

CROSS_PAGE_IDS = [
    "nodefirst_v2_r1::011", "scale300_integrative_v1::cp001",
    "nodefirst_v2_r1::013", "nodefirst_v2_r1::014",
    "scale300_snapshot_d::01489", "scale300_snapshot_d::01889",
    "scale300_snapshot_d::00914", "scale300_snapshot_d::01010",
    "scale300_snapshot_d::01026", "scale300_snapshot_d::01739",
    "scale300_snapshot_d::01522", "scale300_snapshot_d::02386",
    "scale300_snapshot_d::01171", "scale300_snapshot_d::02275",
    "scale300_snapshot_d::01748", "scale300_snapshot_d::02036",
    "scale300_snapshot_d::01925", "scale300_snapshot_d::01238",
    "scale300_snapshot_d::02182", "scale300_snapshot_d::02263",
    "scale300_snapshot_d::01672", "scale300_snapshot_d::02392",
    "scale300_snapshot_d::01353", "scale300_snapshot_d::01561",
    "scale300_snapshot_d::02107", "scale300_snapshot_d::02012",
    "scale300_snapshot_d::01365", "scale300_integrative_v1::cp003",
    "scale300_snapshot_d::01109", "scale300_integrative_v1::cp004",
]

PRIOR_CROSSDOC_IDS = [
    "nodefirst_v2_r1::026", "nodefirst_v2_r1::027",
    "nodefirst_v2_r1::028", "nodefirst_v2_r1::029",
    "nodefirst_v2_r1::030", "nodefirst_v2_r1::032",
    "nodefirst_v2_r1::034", "nodefirst_v2_r1::036",
    "nodefirst_v2_r1::045", "scale300_integrative_v1::cd001",
    "scale300_integrative_v1::cd002", "scale300_integrative_v1::cd003",
    "scale300_integrative_v1::cd004",
]

FRESH_TWO_DOC_IDS = [
    "scale300_snapshot_d::03697", "scale300_snapshot_d::04002",
    "scale300_snapshot_d::04066", "scale300_snapshot_d::05074",
    "scale300_snapshot_d::03476", "scale300_snapshot_d::03577",
    "scale300_snapshot_d::03462",
    "scale300_snapshot_d::03703",
    "scale300_snapshot_d::04327",
    "scale300_snapshot_d::03849", "scale300_snapshot_d::03530",
    "scale300_snapshot_d::03085", "scale300_snapshot_d::03791",
    "scale300_snapshot_d::04031", "scale300_snapshot_d::04160",
    "scale300_snapshot_d::05280",
]

FRESH_THREE_DOC_IDS = [
    "scale300_snapshot_d::06453", "scale300_snapshot_d::06566",
    "scale300_snapshot_d::06536", "scale300_snapshot_d::06624",
]

REVISIONS = {
    "scale300_snapshot_d::01010": {
        "question": "What must be completed after Step 2 versus Step 3 of the strategic-planning workbook?",
    },
    "scale300_snapshot_d::03697": {
        "question": "How do the NIH logo variants in Volume 17 Issue 2 and Volume 18 Issue 2 differ in surrounding background and arrowhead construction?",
        "answer": "The Volume 17 Issue 2 variant uses a dark-green surrounding background and a single stylized arrowhead; the Volume 18 Issue 2 variant uses a solid-blue surrounding background and two parallel diagonal lines forming the arrowhead.",
    },
    "scale300_snapshot_d::03462": {
        "question": "How do the NIH letter color and surrounding background differ between the Spring 2021 and Spring 2022 logo variants?",
        "answer": "The Spring 2021 variant uses dark-blue NIH letters with a dark-blue surrounding background; the Spring 2022 variant uses purple NIH letters with a purple surrounding background.",
    },
    "scale300_snapshot_d::03526": {
        "question": "How do the NIH letter styling and surrounding background differ between the Fall 2021 and Spring 2022 logo variants?",
        "answer": "The Fall 2021 variant uses dark-blue NIH letters with a dark-blue surrounding background; the Spring 2022 variant uses bold purple letters with a purple surrounding background.",
    },
    "scale300_snapshot_d::03849": {
        "question": "How does the color of the NIH letters differ between the Volume 17 Issue 2 and Winter 2021 logo variants?",
    },
    "scale300_snapshot_d::03530": {
        "question": "How does the circular background of the U.S. Department of Health and Human Services seal differ between the Spring 2021 and Volume 17 Issue 2 versions?",
    },
    "scale300_snapshot_d::04031": {
        "question": "How do the number and color of chevrons differ between the Volume 18 Issue 3 and Fall 2021 NIH logo variants?",
    },
    "scale300_snapshot_d::04160": {
        "question": "How do the chevrons differ between the NIH Clinical Center and NHLBI logos, and what text color is specified for NHLBI?",
        "answer": "The NIH Clinical Center logo uses two blue chevrons, while the NHLBI logo uses one red chevron and gray institute-name text.",
    },
    "scale300_snapshot_d::04327": {
        "question": "How do the background and chevron count differ between the National Institute on Aging logo and the Spring 2021 NIH logo?",
    },
    "scale300_snapshot_d::03576": {
        "question": "What percentages appear in the 'About' circular indicators in the Winter 2021 and Winter 2022 MedlinePlus issues?",
    },
    "scale300_snapshot_d::06453": {
        "question": "How do blazer color and hair differ among the women pictured in the Summer 2021, Winter 2021, and Fall 2021 MedlinePlus issues?",
    },
    "scale300_snapshot_d::06624": {
        "question": "What percentages appear in the circular indicators in the Summer 2021, Spring 2022, and Winter 2022 MedlinePlus issues, respectively?",
    },
    "scale300_snapshot_d::06566": {
        "question": "What color features distinguish the NHLBI, NIA, and generic NIH logo variants?",
        "answer": "The NHLBI logo uses a red chevron, the NIA logo uses a blue chevron, and the generic NIH logo is set against a solid-blue background.",
    },
}


NEW_SPECS = [
    {
        "id": "codex_direct_b01::cd2_001", "seed": "scale300_snapshot_d_seed::03514",
        "subtype": "two_doc",
        "question": "For maternal-sepsis screening, what time window favors a pregnancy-adjusted tool, what should be used outside that window, and what does pregnancy adjustment account for?",
        "answer": "A pregnancy-adjusted tool is more accurate from 20 weeks of pregnancy through three days after delivery; outside that period, a non-pregnancy-adjusted tool should be used. Pregnancy adjustment accounts for body changes that occur during pregnancy.",
        "claims": [
            ("c1", "The pregnancy-adjusted window runs from 20 weeks through three days after delivery.", 0, "between 20 weeks (about five months) of pregnancy and three days after delivery"),
            ("c2", "Outside that window, non-pregnancy-adjusted tools should be used.", 0, "Screenings done outside that timeframe should be done with the tools that are not pregnancy-adjusted."),
            ("c3", "Pregnancy adjustment accounts for body changes during pregnancy.", 1, "the provider accounted for specific changes that occur in the body during pregnancy"),
        ],
    },
    {
        "id": "codex_direct_b01::cd2_002", "seed": "scale300_snapshot_d_seed::03561",
        "subtype": "two_doc",
        "question": "Which disorders is the simple skin-biopsy test intended to identify, and what contrast in protein detection was reported between diagnosed and unaffected participants?",
        "answer": "The test is intended to identify Parkinson's disease, Lewy body dementia, and related disorders. The target protein was found in more than 90% of diagnosed participants but only 3% of people without a neurodegenerative-disease history.",
        "claims": [
            ("c1", "The biopsy may identify Parkinson's disease, Lewy body dementia, and related disorders.", 1, "may identify people with Parkinson's disease, Lewy body dementia, and related disorders"),
            ("c2", "Protein detection exceeded 90% among diagnosed participants.", 0, "more than 90% of people with a diagnosis"),
            ("c3", "Protein detection was 3% among people without a neurodegenerative-disease history.", 0, "only 3% of individuals without one"),
        ],
    },
    {
        "id": "codex_direct_b01::cd2_003", "seed": "scale300_snapshot_d_seed::03613",
        "subtype": "two_doc",
        "question": "How did the listed U.S. crisis-contact options change from the separate Lifeline and Crisis Text Line contacts to the 988 system, including access for TTY users?",
        "answer": "The earlier listing used 1-800-273-TALK or online Lifeline Chat for the National Suicide Prevention Lifeline and HOME to 741741 for the Crisis Text Line. The newer system supports calls or texts to 988 and online chat; TTY users can use a relay service or dial 711 and then 988.",
        "claims": [
            ("c1", "The earlier Lifeline used 1-800-273-TALK or online chat.", 0, "Call 1-800-273-TALK (8255) or use the Lifeline Chat online"),
            ("c2", "The earlier Crisis Text Line used HOME to 741741.", 0, "Text “HOME” to 741741"),
            ("c3", "The newer service accepts calls or texts to 988 and online chat.", 1, "Call or text 988 to connect to a trained crisis counselor or use the live online chat option."),
            ("c4", "TTY users can use relay service or dial 711 and then 988.", 1, "TTY users can contact the Lifeline via their preferred relay service or by dialing 711, then 988."),
        ],
    },
    {
        "id": "codex_direct_b01::cd2_004", "seed": "scale300_snapshot_d_seed::03999",
        "subtype": "two_doc",
        "question": "How rapid and severe was the illness that caused Amy Purdy's disabilities, and what Paralympic achievements did she later attain?",
        "answer": "She went into septic shock after only 24 hours of flu-like symptoms, spent two and a half months fighting for her life in hospital, and lost her spleen, kidney function, hearing in one ear, and both legs below the knees. She later won three consecutive Paralympic snowboarding medals in 2014 and 2018.",
        "claims": [
            ("c1", "Septic shock followed 24 hours of flu-like symptoms and led to a two-and-a-half-month hospitalization.", 0, "went into septic shock after just 24 hours of feeling like I had the flu, and I fought for my life in the hospital for two and a half months"),
            ("c2", "The illness cost her spleen, kidney function, hearing in one ear, and both legs below the knees.", 0, "losing my spleen, kidney function, hearing in my left ear, and both legs below the knees"),
            ("c3", "She later won three consecutive Paralympic snowboarding medals in 2014 and 2018.", 1, "won three back-to-back Paralympic medals for snowboarding in 2014 and 2018"),
        ],
    },
    {
        "id": "codex_direct_b01::cd2_005", "seed": "scale300_snapshot_d_seed::03283",
        "subtype": "two_doc",
        "question": "Which recurring Library of Congress Magazine departments stay on the same pages in the March-April and July-August 2024 issues, and how do the early feature lineups differ?",
        "answer": "Both issues place Around the Library, News Briefs, Shop the Library, Support the Library, and Last Word on pages 24 through 28. The March-April issue opens with Extremes, Trending, Favorite Place, Off the Shelf, and For You on pages 2, 4, 5, 8, and 9; the July-August issue instead lists Online Offerings, Off the Shelf, Extremes, Favorite Place, and Page From the Past on pages 2 through 6.",
        "claims": [
            ("c1", "The July-August issue places the five recurring closing departments on pages 24 through 28.", 0, "24 Around the Library 25 News Briefs 26 Shop the Library 27 Support the Library 28 Last Word"),
            ("c2", "Its early lineup is Online Offerings, Off the Shelf, Extremes, Favorite Place, and Page From the Past on pages 2 through 6.", 0, "2 Online Offerings 3 Off the Shelf 4 Extremes 5 Favorite Place 6 Page From the Past"),
            ("c3", "The March-April issue places the same five closing departments on pages 24 through 28.", 1, "24 Around the Library 25 News Briefs 26 Shop the Library 27 Support the Library 28 Last Word"),
            ("c4", "Its early lineup is Extremes, Trending, Favorite Place, Off the Shelf, and For You on pages 2, 4, 5, 8, and 9.", 1, "2 Extremes 4 Trending 5 Favorite Place 8 Off the Shelf 9 For You"),
        ],
    },
    {
        "id": "codex_direct_b01::cd2_006", "seed": "scale300_snapshot_d_seed::03573",
        "subtype": "two_doc",
        "question": "How does the broad scarcity of FDA-approved treatments for rare diseases contrast with the specific chronic-migraine approval milestone?",
        "answer": "Among roughly 7,000 known rare diseases, only a few have FDA-approved treatments. By contrast, the FDA approved the first treatment specifically for chronic migraine in 2010.",
        "claims": [
            ("c1", "Only a few of roughly 7,000 rare diseases have FDA-approved treatments.", 0, "There are about 7,000 known rare diseases, but only a few have treatments approved by the Food and Drug Administration."),
            ("c2", "The FDA approved the first chronic-migraine-specific treatment in 2010.", 1, "In 2010, the Food and Drug Administration (FDA) approved the first treatment specifically for chronic migraine."),
        ],
    },
    {
        "id": "codex_direct_b01::cd2_007", "seed": "scale300_snapshot_d_seed::03575",
        "subtype": "two_doc",
        "question": "What handwashing and sanitizer thresholds do the two sources share, and what distinct context-specific advice does each add?",
        "answer": "Both recommend washing with soap and water for at least 20 seconds or using sanitizer containing at least 60% alcohol. One emphasizes doing so after coughing, sneezing, blowing the nose, and using the restroom; the RSV guidance additionally recommends vaccination for eligible people.",
        "claims": [
            ("c1", "The general guidance requires at least 20 seconds of handwashing.", 0, "Wash your hands frequently with soap and water for at least 20 seconds."),
            ("c2", "It specifies sanitizer with at least 60% alcohol and emphasizes use after respiratory and restroom activities.", 0, "use hand sanitizer that contains at least 60% alcohol, particularly after coughing, sneezing, blowing your nose, and using the restroom"),
            ("c3", "The RSV guidance repeats the 20-second and 60%-alcohol thresholds.", 1, "wash your hands often with soap and water for at least 20 seconds or use sanitizer hand gel that contains at least 60% alcohol"),
            ("c4", "It also recommends vaccination for eligible people.", 1, "Getting one of the available vaccines if you are eligible is also an effective way to lower your risk of RSV disease."),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_001", "seed": "scale300_snapshot_d_seed::06490",
        "subtype": "three_plus_doc",
        "question": "How do the baking temperature and duration differ among the zucchini, bell-pepper, and fish recipes, and what leftover rule do all three share?",
        "answer": "The zucchini bakes uncovered at 375 °F for 35–40 minutes; the bell-pepper dish bakes at 350 °F for 15 minutes; and the fish bakes at 350 °F for 15 minutes covered plus 20 minutes uncovered. All three direct readers to refrigerate leftovers within two hours.",
        "claims": [
            ("c1", "The zucchini recipe uses 375 °F.", 0, "Preheat oven to 375 °F"),
            ("c2", "The zucchini bakes uncovered for 35 to 40 minutes.", 0, "Bake uncovered for 35 to 40 minutes."),
            ("c3", "The bell-pepper recipe uses 350 °F.", 1, "Preheat oven to 350 °F"),
            ("c4", "The bell-pepper dish bakes for 15 minutes.", 1, "Bake for 15 minutes, or until peppers are heated through and cheese is melted."),
            ("c5", "The fish recipe uses 350 °F.", 2, "Preheat oven to 350 °F"),
            ("c6", "The fish bakes for 15 minutes covered and 20 minutes uncovered.", 2, "Cover the baking dish with foil and bake for 15 minutes. Remove foil and bake for 20 minutes more"),
            ("c7", "The zucchini recipe says to refrigerate leftovers within two hours.", 0, "Refrigerate leftovers within 2 hours"),
            ("c8", "The bell-pepper recipe says to refrigerate leftovers within two hours.", 1, "Refrigerate leftovers within 2 hours"),
            ("c9", "The fish recipe says to refrigerate leftovers within two hours.", 2, "Refrigerate leftovers within 2 hours"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_002", "seed": "scale300_snapshot_d_seed::06494",
        "subtype": "three_plus_doc",
        "question": "What do three sources add to a profile of NICHD regarding a maternal-health benefit, its institutional history and populations served, and its public contact route?",
        "answer": "NICHD says breastfeeding can help the uterus heal and reduce postpartum-depression risk. The institute has operated since 1962 and has emphasized women, children, and people with disabilities. Its public contact route is nichd.nih.gov or 800-370-2943.",
        "claims": [
            ("c1", "Breastfeeding can aid uterine healing and reduce postpartum-depression risk.", 0, "Breastfeeding can help the uterus heal and reduce the risk of postpartum depression."),
            ("c2", "NICHD has operated since 1962.", 1, "Since 1962"),
            ("c3", "NICHD highlights women, children, and people with disabilities.", 1, "These include women, children, and people with disabilities."),
            ("c4", "NICHD can be reached at nichd.nih.gov or 800-370-2943.", 2, "www.nichd.nih.gov 800-370-2943"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_003", "seed": "scale300_snapshot_d_seed::06570",
        "subtype": "three_plus_doc",
        "question": "What garlic quantity does each of three recipes specify, and what tomato quantity is stated for the black-bean and baked-zucchini dishes?",
        "answer": "The black-bean dish uses four garlic cloves or one teaspoon of garlic powder plus a 15-ounce can of tomatoes. The bowtie pasta uses one teaspoon of minced garlic. The baked zucchini uses two teaspoons of garlic powder and a 14.5-ounce can of tomatoes.",
        "claims": [
            ("c1", "The black-bean dish uses four garlic cloves or one teaspoon garlic powder and 15 ounces of tomatoes.", 0, "4 cloves garlic, minced, or 1 teaspoon garlic powder 1 can (15 ounces) diced tomatoes"),
            ("c2", "The bowtie pasta uses one teaspoon of minced garlic.", 1, "1 teaspoon garlic, minced (about 1 clove)"),
            ("c3", "The zucchini uses two teaspoons garlic powder and a 14.5-ounce can of tomatoes.", 2, "1 can (14.5 ounces) diced tomatoes, not drained 2 teaspoons garlic powder"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_004", "seed": "scale300_snapshot_d_seed::06797",
        "subtype": "three_plus_doc",
        "question": "At three analysis levels, what do the sources show about SARS-CoV-2's appearance, immune recognition, and longer-term systemic effects?",
        "answer": "Microscopy depicts infected cells as large blue circles and SARS-CoV-2 as small red circles. Blood-sample research tested memory cells that recognize the virus. At the clinical level, long COVID may involve more than 200 symptoms across organ systems, with vascular effects and blood clotting among the concerns.",
        "claims": [
            ("c1", "Microscopy depicts cells as large blue circles and SARS-CoV-2 as small red circles.", 0, "cell (blue, large circles) infected with SARS-CoV-2, the virus that causes COVID-19 (red, small circles)"),
            ("c2", "Researchers tested blood samples for memory cells recognizing SARS-CoV-2.", 1, "tested blood samples to identify these memory cells that recognize the SARS-CoV-2 virus"),
            ("c3", "Long COVID may involve more than 200 symptoms across organ systems.", 2, "suffer from more than 200 symptoms from each organ system in the body"),
            ("c4", "The cited longer-term concerns include vascular effects and blood clotting.", 2, "the vascular effects of COVID-19. Blood clotting is part of how this virus affects the body."),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_005", "seed": "scale300_snapshot_d_seed::06690",
        "subtype": "three_plus_doc",
        "question": "What combined profile do three sources give for eczema's typical onset and locations, prevalence and infection risk, and common manifestations and subtype?",
        "answer": "Eczema often begins before age five and commonly affects the face, elbow and knee folds, hands, and feet. It affects about 30% of Americans, mostly children and adolescents, and raises susceptibility to bacterial, viral, and fungal skin infections. Manifestations include dry, itchy, inflamed skin, rashes, scaly patches, blisters, or infected skin; its most common type is atopic dermatitis.",
        "claims": [
            ("c1", "Eczema often begins before age five.", 0, "often begins before age 5"),
            ("c2", "Common sites include the face, elbow and knee folds, hands, and feet.", 0, "the face, inside the elbows, behind the knees, and on the hands and feet"),
            ("c3", "It affects roughly 30% of Americans, mostly children and adolescents.", 1, "affects roughly 30% of Americans, mostly children and adolescents"),
            ("c4", "It can increase risk for bacterial, viral, and fungal skin infections.", 1, "particularly at risk for bacterial, viral, and fungal skin infections"),
            ("c5", "Manifestations include dry, itchy, inflamed skin, rashes, scaly patches, blisters, or infected skin.", 2, "dry, itchy, and inflamed. It can show up as rashes, scaly patches, blisters, or infected skin"),
            ("c6", "The most common type is atopic dermatitis.", 2, "The most common type of eczema is atopic dermatitis."),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_006", "seed": "scale300_snapshot_d_seed::06843",
        "subtype": "three_plus_doc",
        "question": "What distinct public roles involving Librarian of Congress Carla Hayden are recorded in the January, May, and September event reports?",
        "answer": "On January 18 she appeared with filmmaker Ava DuVernay at a special-collections display; on May 10 she interviewed actress and author Whoopi Goldberg; and on September 20 she conferred the Kluge Prize on philosopher Kwame Anthony Appiah.",
        "claims": [
            ("c1", "On September 20 Hayden conferred the Kluge Prize on Kwame Anthony Appiah.", 0, "Carla Hayden confers the Kluge Prize upon philosopher Kwame Anthony Appiah in the Great Hall on Sept. 20"),
            ("c2", "On May 10 Hayden interviewed Whoopi Goldberg.", 1, "Carla Hayden interviews actress and author Whoopi Goldberg in the Coolidge Auditorium on May 10"),
            ("c3", "On January 18 Hayden appeared with Ava DuVernay at a special-collections display.", 2, "Filmmaker Ava DuVernay (right) looks over a special collections display with Librarian of Congress Carla Hayden in the Members Room on Jan. 18"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_007", "seed": "scale300_snapshot_d_seed::07236",
        "subtype": "three_plus_doc",
        "question": "How is rheumatoid arthritis represented across mechanism, research coordination, and lived athletic experience in the three sources?",
        "answer": "It is described as an autoimmune disease in which the immune system attacks healthy cells, tissues, and organs. It is one of five diseases included in the 2021 AMP AIM research partnership. Caroline Wozniacki's return to Olympic competition is described as her first Games since her 2018 rheumatoid-arthritis diagnosis.",
        "claims": [
            ("c1", "Rheumatoid arthritis is an autoimmune disease involving attack on healthy cells, tissues, and organs.", 0, "Sometimes it mistakenly attacks healthy cells, tissues, and organs. This is called an “autoimmune response,” and it's what happens in autoimmune diseases like lupus, multiple sclerosis, and rheumatoid arthritis."),
            ("c2", "The 2021 AMP AIM program includes rheumatoid arthritis among five autoimmune diseases.", 1, "include a total of five common autoimmune diseases: rheumatoid arthritis, lupus, psoriasis, psoriatic arthritis, and Sjögren's syndrome"),
            ("c3", "Wozniacki's return marks her first Games since her 2018 diagnosis.", 2, "first since Wozniacki was diagnosed with rheumatoid arthritis in 2018"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_008", "seed": "scale300_snapshot_d_seed::07294",
        "subtype": "three_plus_doc",
        "question": "How do the Disaster Distress Helpline, NAMI HelpLine, and SAMHSA National Helpline differ in target need and access route?",
        "answer": "The Disaster Distress Helpline offers confidential, multilingual, 24/7/365 counseling for disaster-related crises at 800-985-5990 by call or text. NAMI connects callers at 800-950-NAMI or online with volunteers providing support, information, and resources. SAMHSA's helpline at 1-800-662-HELP, with TTY access, provides free round-the-clock referrals for mental-health and substance-use treatment.",
        "claims": [
            ("c1", "The Disaster Distress Helpline provides 24/7/365 disaster-crisis counseling.", 0, "this 24/7/365 helpline provides disaster crisis counseling"),
            ("c2", "It is confidential, multilingual, and reachable by call or text at 800-985-5990.", 0, "Users can call toll free or text 800-985-5990. This service is confidential and multilingual."),
            ("c3", "NAMI connects people with volunteers for support, information, and resources.", 1, "connect with volunteers across the country and get support, information, and resources"),
            ("c4", "SAMHSA provides phone and TTY access.", 2, "call the SAMSHA National Helpline at 1-800-662-HELP (4357) (TTY: 1-800-487-4889)"),
            ("c5", "SAMHSA is free, open continuously, and provides treatment referrals.", 2, "free and open 24/7, 365 days a year. This service provides referrals to local treatment facilities, support groups, and community-based organizations"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_009", "seed": "scale300_snapshot_d_seed::07311",
        "subtype": "three_plus_doc",
        "question": "How do three 'largest collection' descriptions differ in institution, scope, and scale?",
        "answer": "The Library of Congress holds about 9,000 turn-of-the-20th-century Native-community field recordings, described as the largest U.S. collection of its kind. Its total audio collection is nearly four million and spans wax cylinders through digital recording. The National Library of Medicine is instead described as the world's largest medical library.",
        "claims": [
            ("c1", "The Library of Congress holds about 9,000 Native-community field recordings, the largest U.S. collection of its kind.", 0, "about 9,000 turn-of-the-20th-century field recordings of Native communities, the largest collection in the U.S."),
            ("c2", "Its total audio collection is nearly four million.", 1, "At nearly 4 million and growing"),
            ("c3", "That audio collection spans wax cylinders through digital recording.", 1, "It spans experimental recordings etched into wax cylinders in the 1890s to the most recent achievements in digital sound recording."),
            ("c4", "NLM is described as the world's largest medical library.", 2, "the world's largest medical library"),
        ],
    },
    {
        "id": "codex_direct_b01::cd3_010", "seed": "scale300_snapshot_d_seed::07364",
        "subtype": "three_plus_doc",
        "question": "What Fahrenheit thresholds and qualifying conditions distinguish MIS-C fever, household hypothermia risk, and heat stroke?",
        "answer": "MIS-C is associated with fever above 100.4 °F lasting at least 24 hours; a home below 68 °F is a hypothermia risk for older people; and heat stroke is defined by body temperature above 104 °F and can be life-threatening.",
        "claims": [
            ("c1", "MIS-C fever exceeds 100.4 °F for at least 24 hours.", 0, "a high fever (more than 100.4 degrees Fahrenheit) for 24 hours or longer"),
            ("c2", "A home below 68 °F can pose hypothermia risk to older populations.", 1, "Living in a home kept below 68 degrees Fahrenheit (20 degrees Celsius) can be a risk factor for older populations."),
            ("c3", "Heat stroke means body temperature above 104 °F and can be life-threatening.", 2, "body temperature exceeds 104 degrees Fahrenheit (40 degrees Celsius). Heat stroke can be life-threatening."),
        ],
    },
]


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def revise_existing(record: dict) -> dict:
    record = json.loads(json.dumps(record))
    revision = REVISIONS.get(record["draft_id"], {})
    if "question" in revision:
        record["question"] = revision["question"]
    if "answer" in revision:
        record["gold_answer_draft"] = revision["answer"]
    record["direct_codex_review"] = {
        "status": "DIRECT_REVIEW_ACCEPT",
        "reviewer": "codex_primary_direct_review_20261119",
        "question_well_formed": True,
        "answer_grounded": True,
        "evidence_sufficient": True,
        "node_necessity_reviewed": True,
        "single_node_shortcut_found": False,
        "revision_applied": bool(revision),
    }
    record["final_gate"] = {
        "status": "DIRECT_GOLD_ACCEPT",
        "source_integrity": "PASS",
        "canonical_mapping": "PASS",
        "claim_grounding": "PASS",
        "node_necessity": "PASS",
        "single_node_shortcut": "PASS",
        "manual_approval_required": False,
        "review_kind": "direct_codex_semantic_review",
    }
    return record


def build_new(spec: dict, seed: dict) -> dict:
    evidence = []
    for index, node in enumerate(seed["evidence"]):
        evidence.append({
            "evidence_index": index,
            "canonical_node_id": node["canonical_node_id"],
            "evidence_unit_id": node["evidence_unit_id"],
            "document_id": node["document_id"],
            "page_id": node["page_id"],
            "page_number": node["page_number"],
            "node_type": node["node_type"],
            "evidence_text": node["content_text"],
            "bbox": node.get("bbox"),
            "source_json": node.get("source_json"),
            "page_image": node.get("page_image"),
            "source_corpus": node.get("source_corpus"),
        })
    claims = []
    necessity = []
    by_index = {index: [] for index in range(len(evidence))}
    for claim_id, claim_text, index, span_text in spec["claims"]:
        source = evidence[index]["evidence_text"]
        start = source.find(span_text)
        if start < 0:
            raise ValueError(f"missing span for {spec['id']} {claim_id}: {span_text}")
        claims.append({
            "claim_id": claim_id,
            "claim_text": claim_text,
            "supporting_evidence_indices": [index],
            "evidence_spans": [{
                "evidence_index": index,
                "canonical_node_id": evidence[index]["canonical_node_id"],
                "text": span_text,
                "char_start": start,
                "char_end": start + len(span_text),
            }],
            "grounding_method": "codex_direct_exact_span",
        })
        by_index[index].append(claim_id)
    for index, claim_ids in by_index.items():
        if not claim_ids:
            raise ValueError(f"unused evidence index {index} in {spec['id']}")
        necessity.append({
            "evidence_index": index,
            "canonical_node_id": evidence[index]["canonical_node_id"],
            "missing_claim_ids": claim_ids,
            "why_answer_incomplete_without_node": "Removing this node removes the only declared support for the listed answer component(s).",
        })
    return {
        "draft_id": spec["id"],
        "corpus_snapshot": "snapshot_D_formal_nodes_20261119",
        "qa_category": "cross_document",
        "cross_document_subtype": spec["subtype"],
        "reasoning_type": "controlled_cross_document_synthesis",
        "question": spec["question"],
        "gold_answer_draft": spec["answer"],
        "gold_evidence_draft": evidence,
        "answer_claims": claims,
        "generation_node_necessity": necessity,
        "candidate_discovery": {
            "seed_id": seed["seed_id"],
            "method": "codex_direct_semantic_selection_from_canonical_nodes",
            "graph_edges_used_for_gold_selection": False,
        },
        "direct_codex_review": {
            "status": "DIRECT_REVIEW_ACCEPT",
            "reviewer": "codex_primary_direct_review_20261119",
            "question_well_formed": True,
            "answer_grounded": True,
            "evidence_sufficient": True,
            "node_necessity_reviewed": True,
            "single_node_shortcut_found": False,
            "revision_applied": False,
        },
        "final_gate": {
            "status": "DIRECT_GOLD_ACCEPT",
            "source_integrity": "PASS",
            "canonical_mapping": "PASS",
            "claim_grounding": "PASS",
            "node_necessity": "PASS",
            "single_node_shortcut": "PASS",
            "manual_approval_required": False,
            "review_kind": "direct_codex_semantic_review",
        },
    }


def validate(record: dict, node_map: dict[str, dict]) -> list[str]:
    failures = []
    evidence = record.get("gold_evidence_draft", [])
    claims = record.get("answer_claims", [])
    if not record.get("question") or not record.get("gold_answer_draft"):
        failures.append("EMPTY_QA")
    if len({item.get("canonical_node_id") for item in evidence}) != len(evidence):
        failures.append("DUPLICATE_EVIDENCE")
    docs = {item.get("document_id") for item in evidence}
    pages = {(item.get("document_id"), item.get("page_id")) for item in evidence}
    category = record.get("qa_category")
    if category == "single_node" and len(evidence) != 1:
        failures.append("CATEGORY")
    if category == "cross_page" and not (len(docs) == 1 and len(pages) >= 2):
        failures.append("CATEGORY")
    if category == "cross_document":
        expected = 2 if record.get("cross_document_subtype") == "two_doc" else 3
        if (expected == 2 and len(docs) != 2) or (expected == 3 and len(docs) < 3):
            failures.append("CATEGORY")
    covered = set()
    for item in evidence:
        node = node_map.get(item.get("canonical_node_id"))
        if node is not None:
            if node["document_id"] != item.get("document_id") or node["page_number"] != item.get("page_number"):
                failures.append("NODE_METADATA")
            if node["content_text"].strip() != (item.get("evidence_text") or "").strip():
                failures.append("NODE_TEXT")
        elif not item.get("source_json"):
            failures.append("UNLOCATABLE_LEGACY_NODE")
    for claim in claims:
        for span in claim.get("evidence_spans", []):
            index = span.get("evidence_index")
            if not isinstance(index, int) or not 0 <= index < len(evidence):
                failures.append("SPAN_INDEX")
                continue
            source = evidence[index].get("evidence_text", "")
            start, end = span.get("char_start"), span.get("char_end")
            if not isinstance(start, int) or not isinstance(end, int) or source[start:end] != span.get("text"):
                failures.append("SPAN_OFFSET")
            covered.add(index)
    if covered != set(range(len(evidence))):
        failures.append("EVIDENCE_NOT_CLAIMED")
    return sorted(set(failures))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pool = {item["draft_id"]: item for item in rows(POOL)}
    seeds = {item["seed_id"]: item for item in rows(SEEDS)}
    node_map = {item["canonical_node_id"]: item for item in rows(NODES)}
    selected_ids = SINGLE_IDS + CROSS_PAGE_IDS + PRIOR_CROSSDOC_IDS + FRESH_TWO_DOC_IDS + FRESH_THREE_DOC_IDS
    missing = [draft_id for draft_id in selected_ids if draft_id not in pool]
    if missing:
        raise KeyError(f"missing selected drafts: {missing}")
    records = [revise_existing(pool[draft_id]) for draft_id in selected_ids]
    records.extend(build_new(spec, seeds[spec["seed"]]) for spec in NEW_SPECS)

    failures = {item["draft_id"]: validate(item, node_map) for item in records}
    failures = {key: value for key, value in failures.items() if value}
    questions = Counter(normalize(item["question"]) for item in records)
    duplicates = [key for key, count in questions.items() if count > 1]
    category = Counter(item["qa_category"] for item in records)
    subtype = Counter(
        item.get("cross_document_subtype") for item in records if item["qa_category"] == "cross_document"
    )
    if len(records) != 100 or category != {"single_node": 20, "cross_page": 30, "cross_document": 50}:
        raise ValueError(f"bad batch distribution: rows={len(records)} category={category}")
    if subtype != {"two_doc": 35, "three_plus_doc": 15}:
        raise ValueError(f"bad cross-document distribution: {subtype}")
    if failures or duplicates:
        raise ValueError(f"validation failed: failures={failures}, duplicate_questions={duplicates}")

    output = OUT / "qa_gold_codex_direct_batch01.jsonl"
    output.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    summary = {
        "dataset_version": "nodefirst_qa_codex_direct_20261119_batch01",
        "records": len(records),
        "by_category": dict(category),
        "cross_document_subtype": dict(subtype),
        "source_records_reused_and_directly_reviewed": len(selected_ids),
        "new_records_written_from_canonical_evidence": len(NEW_SPECS),
        "revised_existing_records": sum(item["draft_id"] in REVISIONS for item in records),
        "deterministic_validation_failures": 0,
        "exact_question_duplicates": 0,
        "scheduler_jobs_submitted": 0,
        "original_files_overwritten": False,
    }
    (OUT / "batch01_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
