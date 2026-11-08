# Vendored UI assets

The operations page loads these files from this host. It does not request a CDN, a package registry, or a font host at demo runtime.

Downloaded from the npm registry on 2026-11-07 and pinned below. Licenses are in `licenses/`.

| File | Package | Version | Upstream | License | SHA-256 |
|---|---|---|---|---|---|
| `echarts.min.js` | `echarts` | 6.1.0 | https://github.com/apache/echarts | Apache-2.0 | `b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0` |
| `tabler.min.css` | `@tabler/core` | 1.7.3 | https://github.com/tabler/tabler | MIT | `00601301716c0bd97acbec6c2b6cb98f257d148063ef168aa06f902b1e7d9ea5` |
| `icons/*.svg` | `@tabler/icons` | 3.50.0 | https://github.com/tabler/tabler-icons | MIT | outline SVGs, unchanged from the package |

`@tabler/core@1.7.3` does not ship a LICENSE file inside the npm tarball. `licenses/tabler-core-MIT.txt` is the MIT text from https://github.com/tabler/tabler (dev branch LICENSE, fetched 2026-11-07). The package.json `license` field is MIT.

## What the page actually uses

Tabler components, not the admin shell: `badge`, `btn`, `btn-sm`, `list-group`, `list-group-item`, `list-group-item-action`. Layout, type, and color are this page's own CSS.

ECharts draws only the observation timeline (scatter, time × sensor category). No other chart library.

Icons, outline set, copied unchanged: `activity`, `alert-triangle`, `antenna`, `clock`, `ear`, `point`, `radio`, `refresh`.
