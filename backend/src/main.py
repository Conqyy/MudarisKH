import os
import sys
import logging
import re
from pathlib import Path

# --- 1. Path Resolution ---
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- 2. Imports ---
from src.config.settings import settings
from src.database.firebase_client import FirebaseClient
from src.agents.exam_generator import ExamGeneratorAgent
from src.utils.compile_pdf import compile_tex_to_pdf

# إعداد السجلات
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MudarisPipeline")

def generate_exam():
    logger.info("🚀 Starting Mudaris PDF Exam Generation Pipeline...")

    db_client = FirebaseClient(settings)
    ai_agent = ExamGeneratorAgent()

    user_id = "sultan_123"
    course_id = "cs464"
    selected_lectures = ["lec_3", "lec_4"]
    exam_id = "test_exam_001"

    logger.info(f"📚 Fetching academic context for Course: {course_id}")
    context = db_client.get_selected_context(user_id, course_id, selected_lectures)
    
    if not context.get("transcripts") or context.get("transcripts") == "No transcripts found.":
        logger.error("❌ Failed to fetch transcripts. Make sure Firebase is seeded properly.")
        return

    logger.info("🧠 AI is analyzing transcripts and generating the PDF document...")
    try:
        topics = ["Convolution Layers", "Backpropagation Concepts"]
        preference = "Generate a short mock exam with exactly 2 questions worth 20 marks total."

        raw_tex = ai_agent.compile_exam(
            academic_data=context, 
            topics=topics, 
            preference=preference, 
            exam_id=exam_id, 
            user_id=user_id, 
            course_id=course_id
        )
        
        extraction_result = ai_agent.extract_and_save_exam_metadata(raw_tex, exam_id, user_id, course_id)
        cleaned_tex = extraction_result.get("cleaned_tex", raw_tex)
        
        # إضافة التعليق السحري لـ LaTeX Workshop لضمان التعرف على الملف كـ Root
        output_file = f"{exam_id}.tex"
        magic_comment = f"% !TEX root = {output_file}\n"
        final_tex = magic_comment + cleaned_tex.strip()
        
        secret_rubrics = extraction_result.get("rubrics", {})
        
        # 3. حفظ الاختبار كملف LaTeX
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(final_tex)
            
        logger.info(f"✅ Exam .tex file generated: {output_file}")

        # 4. تحويل LaTeX → PDF تلقائياً
        pdf_path = compile_tex_to_pdf(output_file)
        if pdf_path:
            logger.info(f"📎 PDF ready: {pdf_path}")
        else:
            logger.warning("⚠️ PDF compilation failed — .tex file is still available.")

        # 5. حفظ معايير التصحيح في قاعدة البيانات
        logger.info("🔒 Saving secret grading rubrics to the database...")
        db_client.save_secret_rubrics(user_id, course_id, exam_id, secret_rubrics)
        
        logger.info("🎉 Pipeline finished!")
        
    except Exception as e:
        logger.error(f"❌ Exam generation failed: {e}")

if __name__ == "__main__":
    generate_exam()