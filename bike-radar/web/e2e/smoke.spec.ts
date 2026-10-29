import { expect, test } from "@playwright/test";

test("home page loads the map", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Bike Radar Danger Map" })).toBeVisible();
  await expect(page.getByTestId("map").locator("canvas.maplibregl-canvas")).toBeVisible();
  expect(errors).toEqual([]);
});
