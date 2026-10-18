import bg from "@/assets/bg_sanctuary.jpg";

/** 背景：圣域（进入圣域时 UI 淡入前的一帧，B09 采集），压暗。 */
export function Background() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
      <div className="absolute inset-0 bg-cover bg-center brightness-[.62] saturate-[.95]" style={{ backgroundImage: `url(${bg})` }} />
      <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,14,32,.62)_0%,rgba(8,14,32,.48)_45%,rgba(8,14,32,.7)_100%)]" />
    </div>
  );
}
