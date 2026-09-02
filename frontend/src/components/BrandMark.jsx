// The product wordmark: "खोला" (Khola, Nepali for "stream/river") set in
// a decorative Devanagari display face (Yatra One) with a gradient fill,
// so the name itself reads as a graphic mark rather than plain UI text --
// the one place in the app where that's intentional. A small Latin
// "khola" caption rides alongside/underneath for readers who don't read
// Devanagari; it never substitutes for the Devanagari mark, only
// supplements it.
export default function BrandMark({ variant = 'nav', as: Tag = 'span' }) {
  return (
    <Tag className={`brand-mark brand-mark--${variant}`}>
      <span className="brand-mark__deva" lang="ne">
        खोला
      </span>
      <span className="brand-mark__latin">khola</span>
    </Tag>
  )
}
