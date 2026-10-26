from django.test import TestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from main.models import SiteSetting
from main.context_processors import site_settings


class SiteSettingTestCase(TestCase):
    def test_singleton_load_and_default_values(self):
        conf = SiteSetting.load()
        self.assertEqual(conf.pk, 1)
        self.assertEqual(conf.name, 'Avingine')
        self.assertEqual(conf.contact_email, 'support@avingine.com')
        self.assertFalse(bool(conf.logo))

    def test_singleton_save_enforces_single_row(self):
        conf1 = SiteSetting.load()
        conf1.name = 'Avingine Pro'
        conf1.save()

        # Trying to create another instance
        conf2 = SiteSetting.objects.create(name='Duplicate')
        self.assertEqual(conf2.pk, 1)
        self.assertEqual(SiteSetting.objects.count(), 1)
        self.assertEqual(SiteSetting.load().name, 'Duplicate')

    def test_singleton_delete_prevented(self):
        conf = SiteSetting.load()
        conf.delete()
        self.assertEqual(SiteSetting.objects.count(), 1)

    def test_context_processor_injection(self):
        factory = RequestFactory()
        request = factory.get('/')
        ctx = site_settings(request)
        self.assertIn('site_settings', ctx)
        self.assertEqual(ctx['site_settings'].name, 'Avingine')

    def test_logo_field_upload(self):
        conf = SiteSetting.load()
        dummy_file = SimpleUploadedFile("brand_logo.svg", b"<svg></svg>", content_type="image/svg+xml")
        conf.logo = dummy_file
        conf.save()
        self.assertTrue(bool(conf.logo))
        self.assertIn("brand_logo", conf.logo.url)
        # Cleanup
        conf.logo.delete(save=False)

    def test_favicon_field_upload(self):
        conf = SiteSetting.load()
        dummy_favicon = SimpleUploadedFile("brand_favicon.ico", b"\x00\x00\x01\x00", content_type="image/x-icon")
        conf.favicon = dummy_favicon
        conf.save()
        self.assertTrue(bool(conf.favicon))
        self.assertIn("brand_favicon", conf.favicon.url)
        # Cleanup
        conf.favicon.delete(save=False)


class MainViewsTestCase(TestCase):
    def test_landing_page_renders_successfully(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'main/landing.html')
        self.assertContains(response, 'Avingine')
        self.assertContains(response, 'Play now')
        self.assertContains(response, 'Cash out before it flies away')
        self.assertContains(response, 'Avingine Multiplier Flight Illustration')

    def test_legal_terms_page_renders(self):
        response = self.client.get('/legal/terms/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'legal/terms.html')
        self.assertTemplateUsed(response, 'legal/base.html')
        self.assertContains(response, 'Terms of Service')
        self.assertContains(response, '1.0')

    def test_legal_privacy_page_renders(self):
        response = self.client.get('/legal/privacy/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'legal/privacy.html')
        self.assertContains(response, 'Privacy Policy')

    def test_legal_responsible_gaming_page_renders(self):
        response = self.client.get('/legal/responsible-gaming/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'legal/responsible_gaming.html')
        self.assertContains(response, 'Responsible Gaming')
        self.assertContains(response, 'Self-Exclusion')

    def test_legal_rules_page_renders(self):
        response = self.client.get('/legal/rules/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'legal/rules.html')
        self.assertContains(response, 'Game & Multiplier Rules')

    def test_legal_aml_page_renders(self):
        response = self.client.get('/legal/aml-kyc/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'legal/aml.html')
        self.assertContains(response, 'Anti-Money Laundering')

