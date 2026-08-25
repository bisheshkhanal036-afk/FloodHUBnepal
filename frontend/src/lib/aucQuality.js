// Standard qualitative bands for an AUC statistic (Yesilnacar & Topal
// 2005 and widely repeated in the same flood/landslide-susceptibility
// literature this project's own criteria already cite -- Kazakis et al.
// 2015, Das 2019). Purely descriptive context alongside the real
// number, never a substitute for it. Shared by ValidationPanel.jsx (a
// real-world AUC) and MeteorComparisonPanel.jsx (a model-agreement AUC)
// -- the same 0.5-1.0 scale means the same thing in both places, so one
// definition rather than two that could quietly drift apart.
export function aucQuality(auc) {
  if (auc >= 0.9) return 'excellent'
  if (auc >= 0.8) return 'very good'
  if (auc >= 0.7) return 'good'
  if (auc >= 0.6) return 'average'
  return 'poor — little better than chance'
}
