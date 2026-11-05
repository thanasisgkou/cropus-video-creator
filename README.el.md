# cropus-video-creator (Ελληνικά)

Παίρνει έναν φάκελο με βίντεο και φωτογραφίες από κινητά και GoPro και βγάζει μια ολοκληρωμένη ταξιδιωτική ταινία
σαν τηλεοπτικό επεισόδιο: κεφάλαια με τίτλους, κινούμενους χάρτες διαδρομής, μουσική ανά κεφάλαιο που χαμηλώνει όταν
μιλάνε, υπότιτλους, ετικέτες, κόμικ γραφικά και τελικό 1080p με ελεγμένη ένταση ήχου.

Είναι μικρά εργαλεία Python + FFmpeg που δουλεύουν με απλά αρχεία JSON. Τις *δημιουργικές* αποφάσεις (ποιες στιγμές,
με ποια σειρά, ποια μουσική, ποια αστεία) τις γράφουν σε αυτά τα JSON AI agents (εμείς χρησιμοποιούμε Claude Code)
ή εσύ με το χέρι. Τα εργαλεία κάνουν το μηχανικό και ακριβές κομμάτι: κατάλογο, proxies, contact sheets, απομαγνητοφώνηση,
χρονολόγιο, render και ελέγχους ποιότητας.

Πλήρης τεκμηρίωση (στα αγγλικά): [README.md](README.md).

## Τι χρειάζεσαι

- Python 3.10+ και FFmpeg 7+ (`ffmpeg`, `ffprobe` στο PATH).
- `pip install -r requirements.txt`
- Προαιρετικά κάρτα NVIDIA (πολύ πιο γρήγορα proxies, master και Whisper). Χωρίς αυτήν όλα τρέχουν στη CPU, πιο αργά.
- 15–40 GB ελεύθερο χώρο για ένα ταξίδι δύο εβδομάδων (ορίζεται με `work_dir`).

## Εγκατάσταση

```bash
git clone https://github.com/thanasisgkou/cropus-video-creator.git
cd cropus-video-creator
python -m venv .venv
# Windows: .venv\Scripts\activate      Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Δοκιμή σε δύο λεπτά (χωρίς δικά σου βίντεο)

```bash
python examples/make_demo.py demo-trip
cd demo-trip
python ../tools/ingest.py
python ../tools/prep_media.py all
python ../tools/music_summary.py
python ../tools/build_film.py edl.json film.json
python ../tools/render_film.py film.json --output demo_preview.mp4
python ../tools/qa_gate.py film.json demo_preview.mp4
```

Άνοιξε το `demo_preview.mp4`: δύο κεφάλαια με τίτλους, ετικέτα, στατικές φωτογραφίες και μουσική.

## Η διαδικασία για τη δική σου ταινία

1. **Φάκελος project** δίπλα στο repo (π.χ. `my-trip/`). Αντίγραψε το `project.example.json` ως `my-trip/project.json`
   και βάλε: ώρα του ταξιδιού (`utc_offset_hours`), φακέλους με τα αρχεία κάθε κινητού/GoPro (`sources`, με
   διαφορετικό `prefix` ο καθένας), δίσκο για τα βαριά αρχεία (`work_dir`). Βάλε μουσική `.mp3` στο `my-trip/music/`.
   Τα πρωτότυπα αρχεία δεν αλλάζουν ποτέ.
2. **Προετοιμασία** (μέσα στο `my-trip/`):
   `ingest.py` (κατάλογος) → `prep_media.py all` (proxies 480p, JPG, contact sheets) → `transcribe.py` (Whisper)
   → `music_summary.py`. Για βαριές δουλειές βάλε μπροστά `safe_run.py`, ώστε να μην κολλάει ο υπολογιστής.
3. **Βλέπουν και διαλέγουν οι agents** (ή εσύ): watchers → day directors → chief plan → chapter editors → υπότιτλοι.
   Τα prompts είναι στο [`briefs/`](briefs) (συμπλήρωσε τα `{{…}}` με τα στοιχεία του ταξιδιού) και το γούστο του
   μοντάζ στο [`docs/EDITING_GUIDE.md`](docs/EDITING_GUIDE.md). Αποτέλεσμα: `edl_part*.json` + `edl_frame.json`.
4. **Build, έλεγχος, render**:
   `merge_edl.py` → `build_film.py edl.json film.json` → `qa_gate.py film.json` →
   `render_film.py film.json --output previews/v1.mp4` → `qa_gate.py film.json previews/v1.mp4`.
   Βλέπεις, γράφεις σχόλια, διορθώνεις, ξαναχτίζεις (ξανα-renderάρονται μόνο τα πλάνα που άλλαξαν).
5. **Τελικό**: `render_film.py film.json --master --output final_1080p.mp4` (διαβάζει τα πρωτότυπα, 1920x1080).

Ποτέ μην στέλνεις έκδοση που αποτυγχάνει στο `qa_gate.py`.

## Ιδιωτικότητα

Όλα τρέχουν τοπικά στον υπολογιστή σου. Το `.gitignore` κρατά έξω από το git βίντεο, φωτογραφίες, μουσική, `analysis/`
και `work/`. Μην ανεβάζεις τον φάκελο του project σε δημόσιο repo.

## Άδεια

MIT — δες [LICENSE](LICENSE).
