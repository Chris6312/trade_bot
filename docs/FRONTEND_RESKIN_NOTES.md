# Frontend Reskin Notes

This pack is a **frontend shell/theme refit** for the Trade_Bot UI.

Included files:
- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `frontend/src/mockData.js`

What it does:
- matches the visual language from the uploaded PNG references: neon glass panels, left navigation rail, center hero module, segmented cards, dark command-room background
- includes the seven PNG-backed pages: Dashboard, Performance, Universe, Strategies, Position, Activity, Settings
- keeps the required controls visible from the project source-of-truth docs, including universe refresh, strategy refresh, reconcile/sync actions, flatten controls, and kill-switch confirmation patterns
- includes drawers and confirmation modal patterns so dangerous actions are not one-click traps

Important:
- this is a **drop-in visual shell** because the current full frontend source tree was not uploaded in this chat
- the data is mocked so the layout can be previewed immediately
- wire your existing API/store layer into the same components or replace the mock data object with live selectors/hooks

Suggested merge approach:
1. back up the current project
2. replace your current `frontend/src/App.jsx` and `frontend/src/styles.css`
3. add `frontend/src/mockData.js`
4. map existing API/store data into the current page sections
5. split the large `App.jsx` into page/components folders after visual verification if desired

Recommended next refinement after visual approval:
- split into `components/`, `pages/`, and `features/`
- replace mock data with live API calls
- connect dangerous buttons to your existing control endpoints
- add route-based navigation if the current app already uses React Router
