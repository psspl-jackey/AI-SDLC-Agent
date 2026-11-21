# NFR checklist skill

Use when extracting requirements. For each item, decide: stated in the input, implied, or missing.
A missing item that changes cost or architecture becomes an NFR gap.

- Performance: response times, load expectations, slow-network behaviour
- Scale: expected users in year one, peak concurrent users, data volume
- Availability: uptime expectation, maintenance windows
- Security: authentication method, roles and permissions, data encryption, audit trail
- Privacy and compliance: personal data handled, consent, deletion, regional laws
- Offline support: what must work without a connection (mobile)
- Accessibility: screen readers, contrast, font scaling
- Languages and localisation: languages, currency, date formats, right-to-left
- Devices and OS: minimum Android and iOS versions, browsers, tablets
- Notifications: push, email, SMS, and their triggers
- Analytics: what must be tracked
- Backup and recovery: backup frequency, restore time
- Hosting and environments: client cloud or ours, staging, production
- Maintenance and support: post-launch support period, update cadence
