// `plotly.js-dist-min` ships no type declarations and `@types/plotly.js`
// only declares the `plotly.js` specifier, so importing the dist-min bundle
// trips TS7016 (implicit any) under `noImplicitAny`. Declare the module so the
// build type-checks; the import stays effectively `any` (same as before).
declare module 'plotly.js-dist-min';
