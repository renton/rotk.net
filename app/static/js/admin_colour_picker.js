// Client-side port of tools/colours.py's randomize_palette logic.
//
// Auto-detects any form on the page that has all three colour inputs
// (input[name="bg_colour"], input[name="font_colour"],
// input[name="border_colour"]) and injects a "Randomize palette"
// button immediately before that form's submit. Clicking the button
// generates a fresh palette using the same HSL ranges and WCAG-
// readable font choice as the Python `randomize-faction-colours` /
// `randomize-role-colours` CLI commands.
//
// Loaded by the Faction, Role, Tag, and URL Type edit pages.
(function () {
    function ready(fn) {
        if (document.readyState !== 'loading') { fn(); return; }
        document.addEventListener('DOMContentLoaded', fn);
    }

    // ---- Hex / RGB / HSL plumbing ------------------------------------

    function pad2(n) {
        n = Math.max(0, Math.min(255, Math.round(n)));
        return (n < 16 ? '0' : '') + n.toString(16);
    }
    function rgbToHex(r, g, b) {
        return '#' + pad2(r) + pad2(g) + pad2(b);
    }
    function hexToRgb(hex) {
        hex = hex.replace(/^#/, '');
        return [
            parseInt(hex.slice(0, 2), 16),
            parseInt(hex.slice(2, 4), 16),
            parseInt(hex.slice(4, 6), 16),
        ];
    }

    // Python's colorsys.hls_to_rgb. Inputs h, l, s in [0, 1]; outputs
    // r, g, b in [0, 1].
    function hlsToRgb(h, l, s) {
        if (s === 0) return [l, l, l];
        var m2 = l <= 0.5 ? l * (1 + s) : l + s - l * s;
        var m1 = 2 * l - m2;
        function v(hue) {
            hue = ((hue % 1) + 1) % 1;
            if (hue < 1 / 6) return m1 + (m2 - m1) * hue * 6;
            if (hue < 1 / 2) return m2;
            if (hue < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - hue) * 6;
            return m1;
        }
        return [v(h + 1 / 3), v(h), v(h - 1 / 3)];
    }

    // Python's colorsys.rgb_to_hls. Inputs r, g, b in [0, 1]; outputs
    // h, l, s in [0, 1].
    function rgbToHls(r, g, b) {
        var maxc = Math.max(r, g, b);
        var minc = Math.min(r, g, b);
        var l = (minc + maxc) / 2;
        if (minc === maxc) return [0, l, 0];
        var s = l <= 0.5
            ? (maxc - minc) / (maxc + minc)
            : (maxc - minc) / (2 - maxc - minc);
        var rc = (maxc - r) / (maxc - minc);
        var gc = (maxc - g) / (maxc - minc);
        var bc = (maxc - b) / (maxc - minc);
        var h;
        if (r === maxc) h = bc - gc;
        else if (g === maxc) h = 2 + rc - bc;
        else h = 4 + gc - rc;
        h = (((h / 6) % 1) + 1) % 1;
        return [h, l, s];
    }

    // WCAG 2.x relative luminance.
    function relativeLuminance(hex) {
        function channel(c) {
            c = c / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        }
        var rgb = hexToRgb(hex);
        return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
    }

    // ---- Palette generation ------------------------------------------
    // Matches tools/colours.py exactly:
    //   - bg: random HSL with S 0.45-0.85, L 0.30-0.70
    //   - font: black or white based on relative luminance (>0.5 → black)
    //   - border: bg with lightness shifted ±0.18 (away from current L)

    function randomBgColour() {
        var h = Math.random();
        var s = 0.45 + Math.random() * (0.85 - 0.45);
        var l = 0.30 + Math.random() * (0.70 - 0.30);
        var rgb = hlsToRgb(h, l, s);
        return rgbToHex(rgb[0] * 255, rgb[1] * 255, rgb[2] * 255);
    }

    function readableFontColour(bgHex) {
        return relativeLuminance(bgHex) > 0.5 ? '#000000' : '#ffffff';
    }

    function deriveBorderColour(bgHex, shift) {
        if (shift === undefined) shift = 0.18;
        var rgb = hexToRgb(bgHex);
        var hls = rgbToHls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255);
        var newL = hls[1] > 0.5 ? hls[1] - shift : hls[1] + shift;
        newL = Math.max(0.05, Math.min(0.95, newL));
        var rgb2 = hlsToRgb(hls[0], newL, hls[2]);
        return rgbToHex(rgb2[0] * 255, rgb2[1] * 255, rgb2[2] * 255);
    }

    function randomizePalette() {
        var bg = randomBgColour();
        return { bg: bg, font: readableFontColour(bg), border: deriveBorderColour(bg) };
    }

    // ---- DOM glue ----------------------------------------------------

    function applyPalette(form, palette) {
        ['bg_colour', 'font_colour', 'border_colour'].forEach(function (name) {
            var input = form.querySelector('input[name="' + name + '"]');
            if (!input) return;
            input.value = (
                name === 'bg_colour' ? palette.bg :
                name === 'font_colour' ? palette.font :
                                         palette.border
            );
            // Fire input + change so any other listeners (e.g. live
            // preview widgets we might add later) pick the swap up.
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }

    function injectButton(form) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-outline-secondary mb-3';
        btn.title = 'Generate a fresh palette (font colour picked for WCAG-readable contrast).';
        btn.innerHTML = '<i class="fa-solid fa-shuffle me-1" aria-hidden="true"></i>Randomize palette';
        btn.addEventListener('click', function () {
            applyPalette(form, randomizePalette());
        });

        // Insert just before the submit button if there is one; else
        // append to the form so it lands at the end.
        var submit = form.querySelector('button[type="submit"], input[type="submit"]');
        if (submit && submit.parentNode) {
            submit.parentNode.insertBefore(btn, submit);
        } else {
            form.appendChild(btn);
        }
    }

    ready(function () {
        Array.prototype.forEach.call(document.querySelectorAll('form'), function (form) {
            if (form.querySelector('input[name="bg_colour"]')
                && form.querySelector('input[name="font_colour"]')
                && form.querySelector('input[name="border_colour"]')) {
                injectButton(form);
            }
        });
    });
})();
