from pptx import Presentation
import os

pptx_paths = [
    r"C:\Users\heyit\Downloads\courses\Neo4j_Campus_Tool_Server_Review_SRM.pptx",
    r"C:\Users\heyit\Downloads\Neo4j_Campus_Tool_Server_Review_SRM.pptx"
]

for p in pptx_paths:
    if not os.path.exists(p):
        continue
    prs = Presentation(p)
    
    # Slide 2 (index 1): 44/44 -> 46/46
    slide2 = prs.slides[1]
    for shape in slide2.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                if "44/44" in para.text:
                    para.text = para.text.replace("44/44", "46/46")
                elif "44 / 44" in para.text:
                    para.text = para.text.replace("44 / 44", "46 / 46")

    # Slide 13 (index 12): Schema
    slide13 = prs.slides[12]
    for shape in slide13.shapes:
        if shape.has_text_frame:
            p_texts = [para.text for para in shape.text_frame.paragraphs]
            full_txt = " ".join(p_texts)
            if "Program / Course" in full_txt or "1,284 modules" in full_txt:
                for para in shape.text_frame.paragraphs:
                    if "1,284 modules" in para.text:
                        para.text = "251 Official Courses (Reg 2021)"
                    elif "Program / Course" in para.text:
                        para.text = "Official Regulations 2021 Courses"

    # Slide 17 (index 16): Results
    slide17 = prs.slides[16]
    for shape in slide17.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                if "44 / 44" in para.text:
                    para.text = para.text.replace("44 / 44", "46 / 46")
                elif "44/44" in para.text:
                    para.text = para.text.replace("44/44", "46/46")

    prs.save(p)
    print(f"Updated {p}")

