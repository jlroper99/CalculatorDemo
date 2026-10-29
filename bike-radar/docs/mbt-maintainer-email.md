# Draft: email to the MyBikeTraffic maintainer (ROADMAP M1)

For Jared to send. Nothing here has been sent.

---

**To:** Dr. Brian Toone (MyBikeTraffic)
**Subject:** Questions about the per-ride CSV export (units, bulk export)

Hi Dr. Toone,

I ride with a Varia and the MyBikeTraffic data field. Thank you for building and running it. I'm
working on a small personal tool that maps which road segments have cars passing faster than the
posted limit, using the per-ride **Export (CSV)** I download while logged in.

So I can describe the data correctly, could you confirm a few things about that export?

1. **Units.** From my own exports, the speeds look like m/s (absolute ≈ relative + rider speed,
   with relative speeds in 3 m/s steps), `approach_range`/`closest_range` look like meters
   (longitudinal), and `passlength` looks like seconds. My account is set to imperial and the
   values still look metric. Is that right for every account, metric and imperial?
2. **`maxspdabs` vs `pass_spdabs`.** What does each represent, and is one better for "how fast
   was the car going when it passed me"?
3. **`car #` stability.** If a ride is reprocessed, can its car numbers change?
4. **Bulk export.** Is there, or could there be, a supported way to export all of my rides at
   once? I won't automate downloads from the site without your permission.

If I ever share results publicly (for example a report to my city), I'll credit MyBikeTraffic and
state that radar speeds are uncalibrated estimates. Please let me know if you'd like it described
differently.

Thanks,
Jared
