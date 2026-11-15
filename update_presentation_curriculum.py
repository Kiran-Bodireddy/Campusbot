from pptx import Presentation
import os

pptx_path = "Neo4j_Campus_Tool_Server_Review_SRM.pptx"
if os.path.exists(pptx_path):
    try:
        prs = Presentation(pptx_path)
        updated_count = 0
        for s_idx, slide in enumerate(prs.slides):
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        # Update test counts
                        for old_t in ["46/46", "46 / 46", "44/44", "44 / 44"]:
                            if old_t in para.text:
                                para.text = para.text.replace(old_t, "49/49")
                                updated_count += 1
                        # Update course counts
                        for old_c in ["251 Official Courses", "251 official courses", "1,284 modules"]:
                            if old_c in para.text:
                                para.text = para.text.replace(old_c, "668 Official SRMIST Courses")
                                updated_count += 1
        prs.save(pptx_path)
        print(f"Successfully updated PPTX with {updated_count} replacements.")
    except Exception as e:
        print(f"PPTX update note: {e}")

