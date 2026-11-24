import base64
import re
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from ..models import Review, canonical
from ..profile import pdf


def recipe(job, forms):
    for f in forms:
        if (
            job.company == f["company"]
            and f.get("permission")
            and urlsplit(job.url).hostname == f["host"]
            and re.fullmatch(f["job_path"], urlsplit(job.url).path)
        ):
            return f
    raise Review(
        "Open the employer listing and apply manually, or configure a permitted form."
    )


@contextmanager
def session(job, form, profile, answers, year, *, live=False):
    # Only a reviewed form definition can select an outbound destination or local file.
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(service_workers="block", accept_downloads=False)
        hosts = {form["host"], *form.get("asset_hosts", [])}
        phase = {"write": False, "private": False, "sent": False}
        upload = {}

        def guard(route):
            req = route.request
            try:
                p = urlsplit(canonical(req.url))
                is_submit = p.hostname == form["host"] and re.fullmatch(
                    form["submit_path"], p.path
                )
                rule = form.get("verification", {})
                verify_write = (
                    phase["sent"]
                    and p.hostname == form["host"]
                    and rule.get("continue_path")
                    and re.fullmatch(rule["continue_path"], p.path)
                )
                if p.hostname not in hosts or (phase["private"] and not live):
                    route.abort()
                    return
                if req.method not in {"GET", "HEAD"} or is_submit:
                    first_submit = is_submit and phase["write"] and not phase["sent"]
                    if not (
                        live and req.method == "POST" and (first_submit or verify_write)
                    ):
                        route.abort()
                        return
                    if first_submit:
                        phase["sent"] = True
                # Screen each response before the browser can follow any redirects.
                options = {}
                if req.method == "POST" and "multipart/form-data" in req.headers.get(
                    "content-type", ""
                ):
                    if not upload or canonical(req.url) != upload["url"]:
                        route.abort()
                        return
                    headers = dict(req.headers)
                    headers.pop("content-length", None)
                    headers["content-type"] = upload["type"]
                    options = {"headers": headers, "post_data": upload["body"]}
                response = route.fetch(max_redirects=0, timeout=15000, **options)
                if 300 <= response.status < 400:
                    route.abort()
                else:
                    route.fulfill(response=response)
            except Exception:
                try:
                    route.abort()
                except Exception:
                    pass

        context.route("**/*", guard)
        context.route_web_socket("**/*", lambda socket: socket.close())
        page = context.new_page()
        page.set_default_timeout(8000)
        try:
            result = page.goto(job.url, wait_until="domcontentloaded")
            if not result or result.status != 200:
                raise Review("Verify that the employer posting is still open.")

            def check_identity():
                identity = page.locator(form["identity"])
                if identity.count() != 1 or not job.identifies(identity.inner_text()):
                    raise Review(
                        "Confirm the employer page identifies the expected opening."
                    )

            check_identity()
            if form.get("apply"):
                page.locator(form["apply"]).click()
            if urlsplit(page.url).hostname != form["host"]:
                raise Review("Review the application destination.")
            root = page.locator(form["form"])
            if root.count() != 1 or page.frames[1:]:
                raise Review("Review the changed or embedded application form.")
            if not root.evaluate(
                "f => f.tagName === 'FORM' && f.method.toUpperCase() === 'POST'"
            ):
                raise Review("Review the employer form submission method.")
            phase["private"] = True
            expected = {}
            for field in form["fields"]:
                selector = field["selector"]
                loc = root.locator(selector)
                if loc.count() != 1:
                    raise Review("Review the changed field " + field["label"] + ".")
                if field["label"] != loc.evaluate(
                    """el => Array.from(el.labels || []).map(x => x.innerText.trim()).join(' ') || el.getAttribute('aria-label') || ''"""
                ):
                    raise Review("Review the employer's changed field label.")
                kind = field.get("kind", "text")
                if kind == "file":
                    key = field["answer"]
                    if key == "resume":
                        key = f"resume_{year}"
                    elif key == "transcript":
                        if not field.get("accepts_unofficial") or not re.search(
                            "transcript", field["label"], re.I
                        ):
                            raise Review(
                                "Confirm whether an unofficial transcript is accepted."
                            )
                    else:
                        raise Review("Review the requested document.")
                    value = pdf(profile, key)
                    loc.set_input_files(str(value))
                    expected[selector] = (kind, value.name)
                else:
                    value = (
                        str(year)
                        if field["answer"] == "graduation_year"
                        else answers.get(field["answer"])
                    )
                    if value is None:
                        raise Review("Approve an answer for " + field["label"] + ".")
                    if kind == "select":
                        loc.select_option(str(value))
                    elif kind == "checkbox":
                        loc.set_checked(value is True)
                    elif kind == "text":
                        loc.fill(str(value))
                    else:
                        raise Review("Review this form control.")
                    expected[selector] = (kind, value)

            def validate():
                controls = root.locator(
                    "input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea,[contenteditable=true]"
                )
                approved = {
                    root.locator(s).evaluate("e => e.outerHTML") for s in expected
                }
                if controls.count() != len(expected) or any(
                    loc.evaluate("e => e.outerHTML") not in approved
                    for loc in controls.all()
                ):
                    raise Review(
                        "Review unmapped application fields before submitting."
                    )
                if page.locator(
                    'iframe,[class*="captcha" i],[id*="captcha" i]'
                ).count():
                    raise Review(
                        "Complete the additional verification on the employer site."
                    )
                for s, (kind, value) in expected.items():
                    loc = root.locator(s)
                    actual = (
                        loc.is_checked()
                        if kind == "checkbox"
                        else loc.evaluate("el => el.files[0]?.name")
                        if kind == "file"
                        else loc.input_value()
                    )
                    if actual != (value if kind == "checkbox" else str(value)):
                        raise Review("Review the filled form values.")
                if not root.evaluate("f => f.tagName==='FORM' && f.checkValidity()"):
                    raise Review("Review employer form validation errors.")
                btn = root.locator(form["submit"])
                if btn.count() != 1 or not btn.is_enabled():
                    raise Review("Check the Submit control.")
                if live and root.evaluate("f => f.enctype === 'multipart/form-data'"):
                    # Chromium omits uploaded bytes in intercepted request.postData.
                    # Snapshot the actual form including the selected files and submitter.
                    packet = root.evaluate(
                        """async (f, selector) => {
                        const button=f.querySelector(selector);
                        const data=new FormData(f, button);
                        const response=new Response(data);
                        const bytes=new Uint8Array(await response.arrayBuffer());
                        let binary='';
                        for(let i=0;i<bytes.length;i+=32768)
                            binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
                        return {body:btoa(binary),type:response.headers.get('content-type'),
                                url:button.getAttribute('formaction') ? button.formAction : f.action};
                    }""",
                        form["submit"],
                    )
                    upload.update(
                        body=base64.b64decode(packet["body"]),
                        type=packet["type"],
                        url=canonical(packet["url"]),
                    )

            validate()
            preview = {f["label"]: expected[f["selector"]][1] for f in form["fields"]}

            if page.locator(form["receipt"]["selector"]).is_visible():
                raise Review("Verify the pre-existing confirmation before submitting.")

            def submit():
                phase["write"] = True
                root.locator(form["submit"]).click(timeout=8000)

            yield page, preview, validate, submit
        except BrowserError as exc:
            raise Review(
                "Inspect the employer form; a required browser step failed."
            ) from exc
        finally:
            browser.close()


def receipt(page, job, rule):
    try:
        loc = page.locator(rule["selector"])
        loc.wait_for(timeout=10000)
        text = loc.inner_text()
        return bool(re.search(rule["pattern"], text, re.I) and job.identifies(text))
    except Exception:
        return False


def verify_challenge(page, rule, gmail, recipient, started, job):
    if not page.locator(rule["challenge"]).is_visible():
        return
    binding = job.req or job.title
    if rule.get("binding_selector"):
        binding = page.locator(rule["binding_selector"]).inner_text().strip()
    if not binding:
        raise Review("Verify the email challenge in the current application.")
    expires = time.monotonic() + 90
    while time.monotonic() < expires:
        hit = gmail().verification(rule, recipient, started, binding)
        if hit:
            _, value = hit
            if rule["kind"] == "code":
                page.locator(rule["input"]).fill(value)
                page.locator(rule["continue"]).click()
            else:
                page.goto(value, wait_until="domcontentloaded")
            return
        time.sleep(5)
    raise Review(
        "Complete the employer's email verification and check whether the submission arrived."
    )
