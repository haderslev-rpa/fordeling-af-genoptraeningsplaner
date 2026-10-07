# fordeling-af-genoptraeningsplaner

## Queue-delen

Kør producer-delen sådan:

```bash
uv run python main.py --queue
```

Producer-delen:

1. Beregner søgeperioden fra `configuration.py`.
2. Henter genoptræningsplaner fra CURA.
3. Beholder kun planer med blank `rehabilitation_subtype`.
4. Finder tilknyttede `CuraSimpleTask`-id'er.
5. Kontrollerer via `q-haderslev-vbo`, om Communication-id allerede
   findes som reference i køen.
6. Opretter kun nye work items.

Worker-delen er ikke implementeret i denne første version.
