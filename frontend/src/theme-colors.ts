const light = {
  primaryColor: "#245ec7",
  primaryColorHover: "#1e50ab",
  primaryColorPressed: "#19438f",
  placeholderColor: "#68717d",
};

const dark = {
  primaryColor: "#85adff",
  primaryColorHover: "#a3c1ff",
  primaryColorPressed: "#6994e8",
  placeholderColor: "#a0a9b5",
};

export function themeColors(isDark: boolean) {
  const colors = isDark ? dark : light;
  return { ...colors, primaryColorSuppl: colors.primaryColorHover };
}
