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

from .context import FLOOD_HISTORY_RADIUS_M
from .profile import CITIZEN_CRITERIA, RISK_DIRECTION, VALIDATION, normalized_weights
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


# --- supporting-evidence copy (context.py) ---

CONTEXT_TEXT = {
    "history_none": {
        "en": "No floods have been officially recorded within {radius_km} km of here since 2011.",
        "ne": "सन् २०११ यता यहाँबाट {radius_km} किमि भित्र कुनै आधिकारिक बाढी अभिलेख छैन।",
    },
    "history_some": {
        "en": "{n} flood(s) officially recorded within {radius_km} km of here since 2011.",
        "ne": "सन् २०११ यता यहाँबाट {radius_km} किमि भित्र {n} वटा बाढी आधिकारिक रूपमा अभिलेख गरिएको छ।",
    },
    "history_caveat": {
        "en": (
            "Records come from BIPAD (NDRRMA, Government of Nepal). Floods are logged where "
            "people report them, so busy areas appear more often than empty ones — an absence "
            "of records is not proof an area is safe."
        ),
        "ne": (
            "अभिलेखहरू BIPAD (NDRRMA, नेपाल सरकार) बाट लिइएको हो। मानिसहरूले खबर गरेको ठाउँमा "
            "मात्र बाढी दर्ता हुन्छ, त्यसैले बाक्लो बस्तीमा बढी देखिन्छ — अभिलेख नहुनुले त्यो ठाउँ "
            "सुरक्षित छ भन्ने प्रमाणित गर्दैन।"
        ),
    },
    "percentile": {
        "en": "This location is more flood-prone than about {pct}% of the Kathmandu Valley.",
        "ne": "यो स्थान काठमाडौं उपत्यकाको करिब {pct}% भन्दा बढी बाढी-जोखिममा छ।",
    },
    "river_context": {
        "en": "The nearest named river is the {name}, about {dist} m away.",
        "ne": "नजिकको नदी {name} हो, करिब {dist} मिटर टाढा।",
    },
    "river_not_a_reason": {
        "en": (
            "Being near a river matters less here than you might expect: in our checks against "
            "real flood records, distance to a river did not predict flooding in this valley. "
            "Most recorded flooding in Kathmandu is drainage failure away from the main channels, "
            "so river distance is shown for orientation only and is not part of the score."
        ),
        "ne": (
            "यहाँ नदीको नजिक हुनुले तपाईंले सोचेभन्दा कम अर्थ राख्छ: वास्तविक बाढी अभिलेखसँग "
            "गरिएको जाँचमा नदीबाटको दूरीले यस उपत्यकामा बाढीको पूर्वानुमान गरेन। काठमाडौंमा "
            "अभिलेख भएका धेरैजसो बाढी मुख्य नदीभन्दा टाढा ढल अवरुद्ध भएर हुने गरेको छ। त्यसैले "
            "नदीको दूरी दिशाबोधका लागि मात्र देखाइएको हो, अंकमा गणना गरिएको छैन।"
        ),
    },
    "criterion_percentile_raises": {
        "en": "higher than {pct}% of the valley",
        "ne": "उपत्यकाको {pct}% भन्दा बढी",
    },
    "criterion_percentile_lowers": {
        "en": "lower than {inv}% of the valley",
        "ne": "उपत्यकाको {inv}% भन्दा कम",
    },
    "how_it_works": {
        "en": (
            "The score combines {n} things about the land itself, each weighted by how much it "
            "matters. Weights come from a published study of this exact watershed (Chaudhary et "
            "al., 2024); the class boundaries are set from the actual spread of values across "
            "the valley, not copied from elsewhere."
        ),
        "ne": (
            "यो अंकले जमिनसम्बन्धी {n} कुरालाई तिनको महत्त्व अनुसार जोडेर बनाइएको हो। महत्त्व "
            "यही जलाधार क्षेत्रको प्रकाशित अध्ययन (Chaudhary et al., 2024) बाट लिइएको हो; "
            "वर्ग सीमाहरू उपत्यकाकै वास्तविक तथ्याङ्कबाट निकालिएको हो।"
        ),
    },
}

CRITERION_LABEL = {
    "hand": {"en": "Height above the nearest stream", "ne": "नजिकको खोलाभन्दा उचाइ"},
    "dem_elevation": {"en": "Elevation", "ne": "समुद्री सतहबाट उचाइ"},
    "dem_slope": {"en": "Steepness of the ground", "ne": "जमिनको ढलान"},
    "twi": {"en": "Tendency to collect water", "ne": "पानी जम्मा हुने प्रवृत्ति"},
    "drainage_density": {"en": "Density of nearby streams", "ne": "वरपरका खोलाको घनत्व"},
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
    criterion_id: str = ""
    criterion_label: str = ""
    percentile: int = -1
    percentile_text: str = ""
    risk_class: int = 0
    weight: float = 0.0


class FloodRecordOut(BaseModel):
    date: str
    distance_m: int
    hazard: str
    place: str | None = None


class FloodHistoryOut(BaseModel):
    count: int
    radius_km: float
    summary: str
    caveat: str
    records: list[FloodRecordOut] = []


class NearestRiverOut(BaseModel):
    name: str
    distance_m: int
    text: str
    not_a_reason_text: str


class HowItWorksOut(BaseModel):
    text: str
    criteria: list[dict]


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

    risk_percentile: int = -1
    percentile_text: str | None = None
    flood_history: FloodHistoryOut | None = None
    nearest_river: NearestRiverOut | None = None
    how_it_works: HowItWorksOut | None = None

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

        def _pct_text(r) -> str:
            """Phrase the percentile by the criterion's own direction, not
            by whether it raised or lowered risk.

            These are different things and conflating them produced a
            real contradiction: elevation at the 20th percentile RAISES
            flood risk (low ground floods), but describing it as "higher
            than 20% of the valley" next to the sentence "among the
            lower-lying ground" reads as nonsense. What the reader needs
            is where the VALUE sits -- lower than 80% of the valley --
            which is precisely why it raises risk.
            """
            if r.percentile < 0:
                return ""
            ascending = RISK_DIRECTION.get(r.criterion_id) == "ascending"
            key = "criterion_percentile_raises" if ascending else "criterion_percentile_lowers"
            return CONTEXT_TEXT[key][lang].format(pct=r.percentile, inv=100 - r.percentile)

        reasons = [
            ReasonOut(
                code=r.code,
                text=REASON_TEXT[r.code][lang].format(value=r.value),
                value=r.value,
                unit=r.unit,
                severity=r.severity,
                criterion_id=r.criterion_id,
                criterion_label=CRITERION_LABEL.get(r.criterion_id, {}).get(lang, r.criterion_id),
                percentile=r.percentile,
                percentile_text=_pct_text(r),
                risk_class=r.risk_class,
                weight=r.weight,
            )
            for r in a.reasons
        ]

        radius_km = round(FLOOD_HISTORY_RADIUS_M / 1000.0, 1)
        n_hist = len(a.flood_history)
        history = FloodHistoryOut(
            count=n_hist,
            radius_km=radius_km,
            summary=(CONTEXT_TEXT["history_some"] if n_hist else CONTEXT_TEXT["history_none"])[lang]
            .format(n=n_hist, radius_km=radius_km),
            caveat=CONTEXT_TEXT["history_caveat"][lang],
            records=[
                FloodRecordOut(date=r.date, distance_m=r.distance_m, hazard=r.hazard, place=r.place)
                for r in a.flood_history[:8]
            ],
        )

        river = None
        if a.nearest_river is not None:
            river = NearestRiverOut(
                name=a.nearest_river.name,
                distance_m=a.nearest_river.distance_m,
                text=CONTEXT_TEXT["river_context"][lang].format(
                    name=a.nearest_river.name, dist=a.nearest_river.distance_m),
                not_a_reason_text=CONTEXT_TEXT["river_not_a_reason"][lang],
            )

        weights = normalized_weights()
        how = HowItWorksOut(
            text=CONTEXT_TEXT["how_it_works"][lang].format(n=len(CITIZEN_CRITERIA)),
            criteria=[
                {
                    "id": cid,
                    "label": CRITERION_LABEL.get(cid, {}).get(lang, cid),
                    "weight_pct": round(100 * weights.get(cid, 0.0)),
                }
                for cid in CITIZEN_CRITERIA
            ],
        )

        return cls(
            **base,
            risk_level=a.risk_level,
            risk_level_text=RISK_LEVEL_TEXT[a.risk_level][lang],
            hazard_class=a.hazard_class,
            risk_score=a.risk_score,
            summary=RISK_SUMMARY[a.risk_level][lang],
            reasons=reasons,
            cache_key=a.cache_key,
            risk_percentile=a.risk_percentile,
            percentile_text=(
                CONTEXT_TEXT["percentile"][lang].format(pct=a.risk_percentile)
                if a.risk_percentile >= 0 else None
            ),
            flood_history=history,
            nearest_river=river,
            how_it_works=how,
            validation=ValidationOut(
                auc=VALIDATION["auc_success_rate"],
                auc_holdout=VALIDATION["auc_prediction_rate_2020plus"],
                n_flood_points=VALIDATION["n_flood_points"],
                inventory_years=VALIDATION["inventory_years"],
                inventory_source=VALIDATION["inventory_source"],
                note=VALIDATION["comparison"],
            ),
        )
