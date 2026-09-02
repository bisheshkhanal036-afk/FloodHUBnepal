// Small reusable mark used in both LandingPage's nav and Sidebar's
// header -- the project's real icon artwork (a shield enclosing a river
// bend, tracing tributaries either side of the main channel), replacing
// an earlier hand-drawn SVG placeholder. Purely decorative, no props
// needed beyond sizing via the `size` prop.
//
// Served straight from /icon.png (public/, same file index.html's own
// favicon link points at) rather than imported from src/assets -- this
// image is used as-is, unprocessed, in both places, so importing a
// second copy through the bundler would just double the ~750KB asset
// for no benefit.
export default function Logo({ size = 32 }) {
  return <img src="/icon.png" width={size} height={size} alt="" className="logo-mark" />
}
