"""Claude javoblari uchun structured output sxemalari (spec 9).

Model faqat shu sxemadagi JSON'ni qaytaradi (`messages.parse(output_format=...)`).
URL'lar sxemada YO'Q: havolalarni backend `source_id` orqali bazadan oladi (spec 10).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_id: str = Field(description="Kontekstdagi <element id=...> qiymati, masalan EL-123")
    claim: str = Field(description="Shu manba tasdiqlaydigan huquqiy da'vo, qisqa")


class AnswerOutput(BaseModel):
    answer_markdown: str = Field(description="Foydalanuvchiga javob, o'zbek tilida; URL yozilmaydi")
    citations: list[Citation] = Field(description="Har bir muhim huquqiy da'vo uchun manba")
    needs_more: list[str] = Field(
        description="Manba yetarli bo'lmasa: qo'shimcha qidirish kerak bo'lgan aniq mavzular (o'zbekcha). Aks holda bo'sh"
    )
    confidence: Literal["high", "medium", "low"]


class QueryRewrite(BaseModel):
    queries: list[str] = Field(
        description="2-4 ta qisqa qidiruv so'rovi, O'zbekiston qonunchiligidagi rasmiy atamalar bilan (lotin, o'zbekcha)"
    )


class DigestPoint(BaseModel):
    matn: str = Field(description="Hujjatdagi bitta muhim qoida, oddiy tilda, 1 gap")
    source_id: str = Field(description="Shu qoida olingan <element id=...> qiymati, masalan EL-123")


class NewsDigest(BaseModel):
    sarlavha: str = Field(description="Yangilik sarlavhasi, oddiy tilda, 90 belgigacha; baho va bo'rttirishsiz")
    mohiyat: str = Field(description="1-2 gap: hujjat nima qiladi va kimga tegishli, faqat matndan")
    bandlar: list[DigestPoint] = Field(description="2-4 ta eng muhim qoida, har biri manba elementi bilan")
    kimga: list[str] = Field(description="Kimga tegishli: 1-4 ta qisqa guruh (masalan: YaTT, qurilish korxonalari)")
    amaliy: str = Field(description="Buxgalter yoki tadbirkor nima qilishi kerak — 1 gap, faqat matndan; "
                                    "matnda bunday talab bo'lmasa bo'sh qator")


class NewsClassification(BaseModel):
    relevant: bool = Field(description="Soliq, buxgalteriya, tadbirkorlik, mehnat yoki bojxona uchun ahamiyatlimi")
    topics: list[str] = Field(description="1-3 ta mavzu: soliq, buxgalteriya, mehnat, bojxona, tadbirkorlik, boshqa")
    summary: str = Field(description="1-2 gaplik faktik xulosa, faqat berilgan matndan; baho va taxminsiz")
