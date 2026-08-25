"""Request/response models for Citizen Mode, including the bilingual
copy the UI renders.

Text lives here rather than in the frontend for one reason: the wording
of a risk statement is part of the model's honesty, not presentation
polish. The caveat that this is historical susceptibility and not a live
warning has to travel with the number it qualifies, in both languages, so
no client can render the answer without it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .profile import VALIDATION
from .service import Assessment

# --- bilingual copy ---------------------------------------------------

RISK_LEVEL_TEXT = {
    "low": {"en": "LOW", "ne": "न्यून"},
    "moderate": {"en": "MODERATE", "ne": "मध्यम"},
    "high": {"en": "HIGH", "ne": "उच्च"},
}

RISK_SUMMARY = {
    "low": {
        "en": "This area has a low history of flood susceptibility.",
        "ne": "यस क्षेत्रमा बाढीको जोखिम ऐतिहासिक रूपमा न्यून छ।",
    },
    "moderate": {
        "en": "This area has a moderate history of flood susceptibility.",
        "ne": "यस क्षेत्रमा बाढीको जोखिम ऐतिहासिक रूपमा मध्यम छ।",
    },
    "high": {
        "en": "This area has a high history of flood susceptibility.",
        "ne": "यस क्षेत्रमा बाढीको जोखिम ऐतिहासिक रूपमा उच्च छ।",
    },
}

# One entry per code in service._REASON_CODE, both directions.
# {value} is substituted with the criterion's actual value at the point.
REASON_TEXT = {
    "hand_low": {
        "en": "The ground here is only about {value} m above the nearest stream or river channel.",
        "ne": "यहाँको जमिन नजिकको खोला वा नदीको सतहभन्दा करिब {value} मिटर मात्र माथि छ।",
    },
    "hand_high": {
        "en": "The ground here sits well above the nearest channel (about {value} m).",
        "ne": "यहाँको जमिन नजिकको खोलाभन्दा निकै माथि छ (करिब {value} मिटर)।",
    },
    "elevation_low": {
        "en": "At about {value} m, this is among the lower-lying ground in the valley.",
        "ne": "करिब {value} मिटरमा रहेको यो ठाउँ उपत्यकाको होचो भागमध्ये पर्छ।",
    },
    "elevation_high": {
        "en": "At about {value} m, this is among the higher ground in the valley.",
        "ne": "करिब {value} मिटरमा रहेको यो ठाउँ उपत्यकाको अग्लो भागमध्ये पर्छ।",
    },
    "slope_flat": {
        "en": "The ground is very flat here (about {value}°), so water drains away slowly.",
        "ne": "यहाँको जमिन निकै समथर छ (करिब {value}°), त्यसैले पानी बिस्तारै बग्छ।",
    },
    "slope_steep": {
        "en": "The ground slopes at about {value}°, so water drains away quickly.",
        "ne": "जमिनको ढलान करिब {value}° छ, त्यसैले पानी छिटो बग्छ।",
    },
    "twi_high": {
        "en": "The shape of the land here collects water running down from higher ground.",
        "ne": "यहाँको भू-बनावटले माथिबाट बग्ने पानी जम्मा गर्छ।",
    },
    "twi_low": {
        "en": "The shape of the land here sheds water rather than collecting it.",
        "ne": "यहाँको भू-बनावटले पानी जम्मा गर्नुभन्दा बगाएर पठाउँछ।",
    },
    "drainage_high": {
        "en": "There is a dense network of streams and channels around this location.",
        "ne": "यस स्थान वरिपरि खोला र नालाहरूको बाक्लो सञ्जाल छ।",
    },
    "drainage_low": {
        "en": "There are few streams or channels around this location.",
        "ne": "यस स्थान वरिपरि खोला वा नालाहरू कम छन्।",
    },
}

NOT_COVERED_TEXT = {
    "en": (
        "This location is outside the Kathmandu Valley pilot area. "
        "FloodHUB does not have an assessment for it yet."
    ),
    "ne": (
        "यो स्थान काठमाडौं उपत्यका परीक्षण क्षेत्रभन्दा बाहिर छ। "
        "FloodHUB सँग यसको मूल्याङ्कन अहिले उपलब्ध छैन।"
    ),
}

# Non-negotiable. Travels with every assessment, in both languages.
DISCLAIMER = {
    "en": (
        "This shows which areas have historically tended to flood, based on the shape of the land "
        "and past flood records. It is NOT a live flood warning and does not know about current "
        "conditions or the weather right now. It also cannot know about a blocked drain, a new "
        "wall, or recent construction near you. For current alerts, contact DHM "
        "(hydrology.gov.np) or BIPAD (bipadportal.gov.np)."
    ),
    "ne": (
        "यसले जमिनको बनावट र विगतका बाढीका अभिलेखका आधारमा कुन क्षेत्रहरूमा ऐतिहासिक रूपमा बाढी "
        "आउने गरेको छ भन्ने देखाउँछ। यो प्रत्यक्ष बाढी चेतावनी होइन र हालको अवस्था वा मौसमबारे "
        "जानकारी राख्दैन। यसले बन्द भएको ढल, नयाँ पर्खाल वा नजिकैको नयाँ निर्माणबारे पनि थाहा "
        "पाउँदैन। तत्काल चेतावनीका लागि DHM (hydrology.gov.np) वा BIPAD (bipadportal.gov.np) मा "
        "सम्पर्क गर्नुहोस्।"
    ),
}

EXPERIMENTAL_NOTICE = {
    "en": "Experimental — Kathmandu Valley pilot. Use alongside local knowledge, not instead of it.",
    "ne": "परीक्षणस्वरूप — काठमाडौं उपत्यका पाइलट। स्थानीय जानकारीसँगै प्रयोग गर्नुहोस्।",
}


# --- models -----------------------------------------------------------


class CitizenAssessRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    lang: str = Field("en", pattern="^(en|ne)$")


class ReasonOut(BaseModel):
    code: str
    text: str
    value: float
    unit: str
    severity: str


class ValidationOut(BaseModel):
    auc: float
    auc_holdout: float
    n_flood_points: int
    inventory_years: str
    inventory_source: str
    note: str


class CitizenAssessResponse(BaseModel):
    covered: bool
    lat: float
    lon: float
    lang: str

    risk_level: str | None = None
    risk_level_text: str | None = None
    hazard_class: int | None = None
    risk_score: float | None = None
    summary: str | None = None
    reasons: list[ReasonOut] = []

    message: str | None = None
    disclaimer: str
    experimental_notice: str
    validation: ValidationOut | None = None
    cache_key: str | None = None

    @classmethod
    def from_assessment(cls, a: Assessment, lang: str) -> "CitizenAssessResponse":
        base = dict(
            covered=a.covered,
            lat=a.lat,
            lon=a.lon,
            lang=lang,
            disclaimer=DISCLAIMER[lang],
            experimental_notice=EXPERIMENTAL_NOTICE[lang],
        )

        if not a.covered:
            return cls(**base, message=NOT_COVERED_TEXT[lang])

        reasons = [
            ReasonOut(
                code=r.code,
                text=REASON_TEXT[r.code][lang].format(value=r.value),
                value=r.value,
                unit=r.unit,
                severity=r.severity,
            )
            for r in a.reasons
        ]

        return cls(
            **base,
            risk_level=a.risk_level,
            risk_level_text=RISK_LEVEL_TEXT[a.risk_level][lang],
            hazard_class=a.hazard_class,
            risk_score=a.risk_score,
            summary=RISK_SUMMARY[a.risk_level][lang],
            reasons=reasons,
            cache_key=a.cache_key,
            validation=ValidationOut(
                auc=VALIDATION["auc_success_rate"],
                auc_holdout=VALIDATION["auc_prediction_rate_2020plus"],
                n_flood_points=VALIDATION["n_flood_points"],
                inventory_years=VALIDATION["inventory_years"],
                inventory_source=VALIDATION["inventory_source"],
                note=VALIDATION["comparison"],
            ),
        )
