# Pet health visual identity (beta.2 development)

Edit a pet profile in the interactive Health card to set an optional hex color
(`#RRGGBB`) and local photo path. Empty color restores the existing palette;
empty photo restores the default cat icon. Both are optional in existing profiles.
The selected color also controls the weight graph and progress bar.

Copy personal photos to `/config/www/pets/` in Home Assistant. Use a simple
filename (letters, digits, hyphen or underscore) with jpg, jpeg, png or webp
extension, for example `/local/pets/cat_a.jpg`. No external URL is accepted.
A missing image falls back to the cat icon. No photo contents are stored by the
integration. Keep photos and generated configurations out of Git. Home Assistant
may serve files in `www` without authentication: do not store sensitive images.

The backend saves the optional fields in the existing local health store. Back up
before upgrading. An older integration will reject profiles containing these new
fields; restore the pre-upgrade health file if downgrading. No feeding settings,
cloud requests, reminder behavior or care-record semantics are changed.

After deploying the matching backend, copy the local JS card and set the existing
resource to `/local/mova-pet-health-card.js?v=6`, then reload the browser. No
regeneration of the dashboard or re-import is needed.
