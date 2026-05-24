// Chapter prose inline-tag styling. Lets the reader pick how the
// tagged spans in a chapter render — pill, square, underlined, or
// just-coloured. Choice is persisted in localStorage under
// `rotk.chapterStyle` so it sticks across chapter navigations and
// future visits.
//
// Targets every span with the `text-ref` class (character refs today,
// any future event/location refs that opt in by adding the class).
// Each span carries data-bg / data-font / data-border attributes
// supplied by build_name_ref_html so the JS doesn't have to parse
// the existing inline style — it just reads the source colours and
// rebuilds the inline style from scratch per style choice.
(function () {
    var STORAGE_KEY = 'rotk.chapterStyle';
    var DEFAULT_STYLE = 'pills';
    var STYLES = ['pills', 'squares', 'underline', 'coloured'];

    function getStyle() {
        try {
            var v = localStorage.getItem(STORAGE_KEY);
            return STYLES.indexOf(v) >= 0 ? v : DEFAULT_STYLE;
        } catch (e) { return DEFAULT_STYLE; }
    }
    function setStyle(v) {
        try { localStorage.setItem(STORAGE_KEY, v); } catch (e) {}
    }

    // WCAG-ish relative luminance. ~0 = black, 1 = white. Used to skip
    // colours that would be invisible against the white page background.
    function luminance(hex) {
        if (!hex || hex.charAt(0) !== '#') return 0;
        var s = hex.replace(/^#/, '');
        if (s.length !== 6) return 0;
        function ch(v) {
            v = v / 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * ch(parseInt(s.slice(0,2), 16))
             + 0.7152 * ch(parseInt(s.slice(2,4), 16))
             + 0.0722 * ch(parseInt(s.slice(4,6), 16));
    }

    // For underline / coloured styles where the span has no background:
    // walk bg → border → font and pick the first colour that's readable
    // on white (luminance < 0.85). Fall through to black if nothing
    // qualifies.
    function pickReadable(bg, border, font) {
        var candidates = [bg, border, font];
        for (var i = 0; i < candidates.length; i++) {
            var c = candidates[i];
            if (c && luminance(c) < 0.85) return c;
        }
        return '#000000';
    }

    function applyStyle(span, style) {
        var bg     = span.getAttribute('data-bg')     || '#ffffff';
        var font   = span.getAttribute('data-font')   || '#000000';
        var border = span.getAttribute('data-border') || '#000000';

        // Reset: drop the pill/badge bootstrap classes the default
        // render adds, and clear inline style so we can rebuild.
        span.classList.remove('badge', 'rounded-pill');
        span.style.cssText = '';

        if (style === 'pills') {
            span.classList.add('badge', 'rounded-pill');
            span.style.cssText =
                'background-color:' + bg + ';' +
                'color:' + font + ';' +
                'border:2px solid ' + border + ';';
        } else if (style === 'squares') {
            // .badge gives padding + slight border-radius; override the
            // radius to 0 for square corners.
            span.classList.add('badge');
            span.style.cssText =
                'background-color:' + bg + ';' +
                'color:' + font + ';' +
                'border:2px solid ' + border + ';' +
                'border-radius:0;';
        } else if (style === 'underline') {
            var c1 = pickReadable(bg, border, font);
            span.style.cssText =
                'color:' + c1 + ';' +
                'text-decoration:underline;' +
                'font-weight:bold;';
        } else if (style === 'coloured') {
            var c2 = pickReadable(bg, border, font);
            span.style.cssText =
                'color:' + c2 + ';' +
                'font-weight:bold;';
        }
    }

    function applyAll(style) {
        var refs = document.querySelectorAll('.text-ref');
        for (var i = 0; i < refs.length; i++) applyStyle(refs[i], style);
    }

    function init() {
        var current = getStyle();
        applyAll(current);

        var picker = document.getElementById('chapter-style-picker');
        if (picker) {
            picker.value = current;
            picker.addEventListener('change', function () {
                var v = picker.value;
                if (STYLES.indexOf(v) < 0) return;
                setStyle(v);
                applyAll(v);
            });
        }
    }

    if (document.readyState !== 'loading') init();
    else document.addEventListener('DOMContentLoaded', init);
})();
