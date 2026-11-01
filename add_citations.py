from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


SOURCE = Path(r"C:\Users\oumay\Downloads\Rapport_pfa_Ménara_Préfa.docx")
OUTPUT = Path(r"C:\Users\oumay\Desktop\Prjt_stage_menara\Rapport_pfa_Ménara_Préfa_citations.docx")


def new_run_after(run, text):
    new_r = OxmlElement("w:r")
    if run._r.rPr is not None:
        new_r.append(deepcopy(run._r.rPr))
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    new_r.append(t)
    run._r.addnext(new_r)
    return new_r


def insert_after(paragraph, needle, citation):
    if citation in paragraph.text:
        return False
    for run in paragraph.runs:
        pos = run.text.find(needle)
        if pos >= 0:
            before = run.text[: pos + len(needle)]
            after = run.text[pos + len(needle) :]
            run.text = before
            citation_r = new_run_after(run, f" {citation}")
            if after:
                after_r = OxmlElement("w:r")
                if run._r.rPr is not None:
                    after_r.append(deepcopy(run._r.rPr))
                t = OxmlElement("w:t")
                t.set(qn("xml:space"), "preserve")
                t.text = after
                after_r.append(t)
                citation_r.addnext(after_r)
            return True
    raise ValueError(f"Expression introuvable: {needle!r} dans {paragraph.text!r}")


def append_citation(paragraph, citation):
    if citation in paragraph.text:
        return False
    paragraph.add_run(f" {citation}")
    return True


def add_hyperlink(paragraph, text, url):
    part = paragraph.part
    rel_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rpr.extend([color, underline])
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


doc = Document(SOURCE)
p = doc.paragraphs

# Sources générales sur le traitement intelligent de documents.
append_citation(p[71], "[10]")
append_citation(p[75], "[11]")
append_citation(p[110], "[10]")
append_citation(p[115], "[10, 11]")
insert_after(p[128], "score F1", "[9]")
insert_after(p[233], "démarche itérative", "[10]")
insert_after(p[290], "moteur NLP métier", "[11]")
append_citation(p[292], "[11]")
insert_after(p[336], "traitement OCR complémentaire", "[11]")
insert_after(p[341], "moteur NLP local", "[11]")

# Documentation officielle des technologies employées.
insert_after(p[348], "Python", "[7]")
insert_after(p[350], "Streamlit", "[1]")
insert_after(p[353], "SQLite", "[2]")
insert_after(p[355], "Ollama", "[3]")
insert_after(p[355], "Qwen3 1.7B", "[8]")
insert_after(p[358], "PyPDF2", "[4]")
insert_after(p[358], "pdfplumber", "[5]")
insert_after(p[362], "Pandas", "[6]")
append_citation(p[474], "[11]")

# Deux nouvelles entrées bibliographiques avec liens cliquables.
ref10 = doc.add_paragraph(style=p[555].style)
ref10.add_run(
    "[10] P. Patidar, « Intelligent Document Processing Software: Your 2026 Guide », "
    "DigiParser, mis à jour le 18 avril 2026. Disponible sur : "
)
add_hyperlink(
    ref10,
    "https://www.digiparser.com/blog/intelligent-document-processing-software#start-small-but-make-it-real",
    "https://www.digiparser.com/blog/intelligent-document-processing-software#start-small-but-make-it-real",
)
ref10.add_run(" (consulté le 31 août 2026).")

ref11 = doc.add_paragraph(style=p[555].style)
ref11.add_run(
    "[11] D. Davies, « Intelligent document processing explained (with an end-to-end tutorial) », "
    "Medium, 31 décembre 2025. Disponible sur : "
)
add_hyperlink(
    ref11,
    "https://medium.com/@online-inference/intelligent-document-processing-explained-with-an-end-to-end-tutorial-60e9a8e15484",
    "https://medium.com/@online-inference/intelligent-document-processing-explained-with-an-end-to-end-tutorial-60e9a8e15484",
)
ref11.add_run(" (consulté le 31 août 2026).")

doc.save(OUTPUT)
print(OUTPUT)
