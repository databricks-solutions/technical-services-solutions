import {type ReactNode, useContext} from 'react';
import Heading from '@theme/Heading';
import Link from '@docusaurus/Link';
import {ScrollContext} from '@site/src/pages/index';
import styles from './styles.module.css';

type ServiceItem = {
  title: string;
  path: string;
  description: ReactNode;
  icon: ReactNode;
  color: string;
};

const ServiceList: ServiceItem[] = [
  {
    title: 'Core Platform',
    path: '/docs/core-platform',
    color: '#ff3621',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
      </svg>
    ),
    description: (
      <>
        Platform infrastructure and DevOps processes including CI/CD pipelines,
        Serverless Upgrade paths, and Observability solutions.
      </>
    ),
  },
  {
    title: 'Data Engineering',
    path: '/docs/data-engineering',
    color: '#2272b4',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
      </svg>
    ),
    description: (
      <>
        Data Engineering offerings including Lakeflow workflows,
        Delta Optimization strategies, and Delta Sharing implementations.
      </>
    ),
  },
  {
    title: 'Data Governance',
    path: '/docs/data-governance',
    color: '#00a972',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
    ),
    description: (
      <>
        Governance services including Unity Catalog Setup for new environments
        and Unity Catalog Upgrade for existing workspaces.
      </>
    ),
  },
  {
    title: 'Data Warehousing',
    path: '/docs/data-warehousing',
    color: '#ffab00',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/>
        <rect x="2" y="3" width="20" height="18" rx="2" fill="none" stroke="currentColor" strokeWidth="2"/>
      </svg>
    ),
    description: (
      <>
        DWH solutions: AI/BI for Data Citizens, DBSQL for Admins & Analysts,
        Power BI best practices, and DW Migration with Lakebridge.
      </>
    ),
  },
  {
    title: 'ML & GenAI',
    path: '/docs/ml-genai',
    color: '#98102a',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <circle cx="12" cy="12" r="3"/>
        <path d="M12 2v4m0 12v4M2 12h4m12 0h4m-3.5-6.5L17 7m-10 10l-1.5 1.5M17 17l1.5 1.5M7 7L5.5 5.5" stroke="currentColor" strokeWidth="2" fill="none"/>
      </svg>
    ),
    description: (
      <>
        ML and AI offerings including AI/ML Pipelines, Gen AI Apps development,
        and MLOps/LLMOps best practices.
      </>
    ),
  },
  {
    title: 'Launch Accelerator',
    path: '/docs/launch-accelerator',
    color: '#ff5f46',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09zM12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>
        <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
      </svg>
    ),
    description: (
      <>
        Drive product adoption and grow accounts. Build strong Databricks foundations
        for scale with no extra cost. Accelerate your first use case.
      </>
    ),
  },
  {
    title: 'Workspace Setup',
    path: '/docs/workspace-setup',
    color: '#1b5162',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
    ),
    description: (
      <>
        Cheatsheets, checklists, demo environments (AWS/GCP/Azure),
        knowledge hub, and enablement materials for workspace configuration.
      </>
    ),
  },
];

function ServiceCard({title, path, description, icon, color}: ServiceItem) {
  return (
    <div className={styles.cardCol}>
      <Link to={path} className={styles.cardLink}>
        <div className={styles.card}>
          <div className={styles.cardIconWrapper} style={{'--card-color': color} as React.CSSProperties}>
            <div className={styles.cardIcon}>
              {icon}
            </div>
          </div>
          <div className={styles.cardContent}>
            <Heading as="h3" className={styles.cardTitle}>{title}</Heading>
            <p className={styles.cardDescription}>{description}</p>
          </div>
          <div className={styles.cardArrow}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7"/>
            </svg>
          </div>
          <div className={styles.cardTooltip}>
            <span className={styles.tooltipTitle}>{title}</span>
            <span className={styles.tooltipDescription}>{description}</span>
          </div>
        </div>
      </Link>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  const {showUpArrow} = useContext(ScrollContext);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <section className={styles.features} id="solutions">
      <div className="container">
        <div className={styles.sectionHeader} id="solutions-header">
          <div className={styles.headerWithArrow}>
            <Heading as="h2">STS Solutions</Heading>
            {showUpArrow && (
              <button onClick={scrollToTop} className={styles.scrollUpButton} aria-label="Scroll to top">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 19V5M5 12l7-7 7 7"/>
                </svg>
              </button>
            )}
          </div>
          <p>Ready-to-use code examples and accelerators for your Databricks implementation</p>
        </div>
        <div className={styles.cardGrid}>
          {ServiceList.map((props, idx) => (
            <ServiceCard key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
