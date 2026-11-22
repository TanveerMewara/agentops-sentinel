'use client';

import { ArrowRight, Building2, ExternalLink, MapPin, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { FormEvent, useState } from 'react';

type SearchResult = {
  property: {
    property_id: string; title: string; city: string; locality: string;
    property_type: string; bedrooms: number | null; price_inr: string;
    amenities: string[]; source_uri: string; current_version: number;
  };
  score: number;
  evidence: {
    property_version: number; source_uri: string; matched_terms: string[];
    matched_fields: string[]; applied_filters: Record<string, unknown>;
    embedding_id?: string | null; embedding_model_id?: string | null;
  };
};
type SearchResponse = {
  retrieval_id: string; strategy: string;
  embedding_model_id?: string | null; results: SearchResult[];
};
type Props = {
  connected: boolean;
  onConnect: () => void;
  request: (path: string, init?: RequestInit) => Promise<unknown>;
};

const priceLabel = (value: string) => `₹${new Intl.NumberFormat('en-IN', {
  maximumFractionDigits: 0,
}).format(Number(value))}`;

function safeSource(uri: string): string | null {
  try {
    const url = new URL(uri);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
}

export default function PropertySearchPanel({ connected, onConnect, request }: Props) {
  const [query, setQuery] = useState('');
  const [strategy, setStrategy] = useState<'lexical' | 'vector'>('lexical');
  const [embeddingAlias, setEmbeddingAlias] = useState('estate_embeddings');
  const [city, setCity] = useState('');
  const [propertyType, setPropertyType] = useState('');
  const [minBedrooms, setMinBedrooms] = useState('');
  const [maxPrice, setMaxPrice] = useState('');
  const [amenities, setAmenities] = useState('');
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!connected) { onConnect(); return; }
    setLoading(true); setError(null);
    try {
      const body: Record<string, unknown> = {
        query: query.trim(), strategy, limit: 8,
      };
      if (strategy === 'vector') body.embedding_model_alias = embeddingAlias.trim();
      if (city.trim()) body.city = city.trim();
      if (propertyType) body.property_type = propertyType;
      if (minBedrooms) body.min_bedrooms = Number(minBedrooms);
      if (maxPrice) body.max_price_inr = maxPrice;
      const required = amenities.split(',').map((item) => item.trim()).filter(Boolean);
      if (required.length) body.required_amenities = required;
      const data = await request('/v1/properties/search', {
        method: 'POST', body: JSON.stringify(body),
      }) as SearchResponse;
      setResponse(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Property search failed.');
    } finally { setLoading(false); }
  }

  return <section className="property-intelligence panel" aria-labelledby="property-heading">
    <div className="property-header">
      <div className="property-heading-icon"><Building2 size={20} /></div>
      <div><p className="property-eyebrow">ESTATEFLOW INTELLIGENCE</p><h2 id="property-heading">Find a property with evidence</h2><p>Search listings in this workspace and inspect the source behind each match.</p></div>
      <span className="property-method"><ShieldCheck size={14} />Evidence-backed</span>
    </div>
    <form className="property-form" onSubmit={search}>
      <label className="property-query"><span>Describe what the customer wants</span><div><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} required placeholder="e.g. luxury apartment with pool near golf course" /></div></label>
      <div className="property-filter-heading"><SlidersHorizontal size={15} /><span>Business filters</span></div>
      <div className="property-filters">
        <label><span>Search method</span><select value={strategy} onChange={(event) => setStrategy(event.target.value as 'lexical' | 'vector')}><option value="lexical">Keyword + location</option><option value="vector">Vector similarity</option></select></label>
        {strategy === 'vector' && <label><span>Embedding alias</span><input value={embeddingAlias} onChange={(event) => setEmbeddingAlias(event.target.value)} maxLength={64} required placeholder="estate_embeddings" /></label>}
        <label><span>City</span><input value={city} onChange={(event) => setCity(event.target.value)} maxLength={100} placeholder="Any city" /></label>
        <label><span>Property type</span><select value={propertyType} onChange={(event) => setPropertyType(event.target.value)}><option value="">Any type</option><option value="apartment">Apartment</option><option value="house">House</option><option value="villa">Villa</option><option value="plot">Plot</option><option value="commercial">Commercial</option></select></label>
        <label><span>Min bedrooms</span><input value={minBedrooms} onChange={(event) => setMinBedrooms(event.target.value)} type="number" min="0" max="20" placeholder="Any" /></label>
        <label><span>Max price (₹)</span><input value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} type="number" min="0" step="1" placeholder="No maximum" /></label>
        <label className="property-amenities"><span>Required amenities</span><input value={amenities} onChange={(event) => setAmenities(event.target.value)} placeholder="e.g. pool, gym" /><small>Separate each amenity with a comma.</small></label>
      </div>
      <div className="property-form-foot"><span>{connected ? strategy === 'vector' ? 'Vector search needs current listing embeddings.' : 'Searching your connected workspace' : 'Connect the API to search real listings'}</span><button type="submit" className="primary-button" disabled={loading}>{loading ? 'Searching…' : connected ? 'Find properties' : 'Connect to search'}<ArrowRight size={15} /></button></div>
    </form>
    {error && <p className="property-error" role="alert">{error}</p>}
    {response && <div className="property-results" aria-live="polite">
      <div className="property-results-head"><div><h3>{response.results.length ? `${response.results.length} matching ${response.results.length === 1 ? 'property' : 'properties'}` : 'No matching properties'}</h3><p>{response.results.length ? `Each result points to a listing version and its source. Method: ${response.strategy.replaceAll('_', ' ')}.` : 'Try a wider query or remove a filter.'}</p></div><span className="mono">SEARCH-{response.retrieval_id.slice(0, 8).toUpperCase()}</span></div>
      {response.results.length > 0 && <div className="property-cards">{response.results.map(({ property, evidence }) => {
        const source = safeSource(evidence.source_uri);
        return <article className="property-card" key={property.property_id}>
          <div className="property-card-top"><span className="property-type">{property.property_type}</span><strong>{priceLabel(property.price_inr)}</strong></div>
          <h4>{property.title}</h4><p className="property-location"><MapPin size={13} />{property.locality}, {property.city}{property.bedrooms !== null ? ` · ${property.bedrooms} bedrooms` : ''}</p>
          <div className="property-tags">{property.amenities.slice(0, 4).map((amenity) => <span key={amenity}>{amenity}</span>)}</div>
          <div className="property-citation"><span>Listing version {evidence.property_version}</span><span>{evidence.embedding_model_id ? `Embedding: ${evidence.embedding_model_id}` : evidence.matched_terms.length ? `Matched: ${evidence.matched_terms.join(', ')}` : 'Location similarity match'}</span></div>
          <div className="property-card-foot"><span className="mono">PROPERTY-{property.property_id.slice(0, 8).toUpperCase()}</span>{source && <a href={source} target="_blank" rel="noopener noreferrer">View source<ExternalLink size={13} /></a>}</div>
        </article>;
      })}</div>}
    </div>}
  </section>;
}
