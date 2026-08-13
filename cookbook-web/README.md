# Next.js template

This is a Next.js template with shadcn/ui.

## Adding components

To add components to your app, run the following command:

```bash
npx shadcn@latest add button
```

This will place the ui components in the `components` directory.

## Using components

To use the components in your app, import them as follows:

```tsx
import { Button } from "@/components/ui/button";
```

## Backends

This app talks to two separate FastAPI processes:

- `NEXT_PUBLIC_COOKBOOK_API_URL` (default `http://127.0.0.1:8001`) — `cookbook/api.py`, the hardware-probe/fit wizard at `/`.
- `NEXT_PUBLIC_SERVICE_URL` (default `http://127.0.0.1:8000`) — `service/main.py`, the chat/admin backend at `/admin`.

Copy `.env.local.example` to `.env.local` and adjust if either backend runs on a different host/port.

## Admin chat

`/admin` is the creator's chat interface: the model, a tool-call trace, and a confirm-gate dialog before any write touches `data/character.md` or `data/sources.md`. Requires `service/main.py` running in agent mode.
