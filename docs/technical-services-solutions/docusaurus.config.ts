import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
    title: 'Technical Services Solutions',
    tagline: 'Shared Technical Services - Solutions. Public Repository',
    favicon: 'img/favicon.ico',

    // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
    future: {
        v4: true, // Improve compatibility with the upcoming Docusaurus v4
    },

    // Set the production url of your site here
    url: 'https://databricks-solutions.github.io',
    // Set the /<baseUrl>/ pathname under which your site is served
    // For GitHub pages deployment, it is often '/<projectName>/'
    baseUrl: '/technical-services-solutions',

    // GitHub pages deployment config.
    // If you aren't using GitHub pages, you don't need these.
    organizationName: 'databricks-solutions', // Usually your GitHub org/user name.
    projectName: 'technical-services-solutions', // Usually your repo name.
    deploymentBranch: 'gh-pages',

    onBrokenLinks: 'throw',
    onDuplicateRoutes: 'throw',
    onBrokenAnchors: 'throw',

    markdown: {
        hooks: {
            onBrokenMarkdownLinks: 'throw',
        },
    },

    // Even if you don't use internationalization, you can use this field to set
    // useful metadata like html lang. For example, if your site is Chinese, you
    // may want to replace "en" with "zh-Hans".
    i18n: {
        defaultLocale: 'en',
        locales: ['en'],
    },

    plugins: [
        'docusaurus-lunr-search'
    ],

    presets: [
        [
            'classic',
            {
                docs: {
                    sidebarPath: './sidebars.ts',
                    // Please change this to your repo.
                    // Remove this to remove the "edit this page" links.
                },
                blog: false,
                theme: {
                    customCss: './src/css/custom.css',
                },
            } satisfies Preset.Options,
        ],
    ],

    themeConfig: {
        colorMode: {
            defaultMode: 'light',
            respectPrefersColorScheme: false,
        },
        navbar: {
            title: 'STS - Technical Services Solutions',
            logo: {
                alt: 'Databricks Logo',
                src: 'img/databricks-logo.png',
            },
            items: [
                {
                    type: 'search',
                    position: 'right',
                },
                {
                    href: 'https://github.com/databricks-solutions/technical-services-solutions',
                    position: 'right',

                    className: 'header-github-link',
                    'aria-label': 'GitHub repository',
                },
            ],
        },
        footer: {
            links: [],
            copyright: `Copyright © ${new Date().getFullYear()} Databricks Solutions. Docs built with Docusaurus.`,
        },
        prism: {
            theme: prismThemes.github,
            darkTheme: prismThemes.dracula,
        },
    } satisfies Preset.ThemeConfig,
};

export default config;
